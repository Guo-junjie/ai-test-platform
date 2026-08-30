"""
coverage/collector — 平台启动被测服务(SUT)时的自动覆盖率探针（能力11 自动路径）

设计原则：
- 默认关闭，由环境变量 AUTO_COVERAGE=1 开启；未开启或任意环节失败都安全降级（不影响测试）。
- 在 env_adapters 启动 SUT 容器时，根据技术栈把覆盖率探针注入启动命令：
    * Java (Spring)：在 `java` 之后插入 `-javaagent:/opt/jacoco/jacocoagent.jar=...`
    * Python (Flask/FastAPI/Django)：用 `coverage run` 包裹原启动命令
- 测试跑完后，从容器把覆盖率数据拷出、转成 XML、解析并入库（source=AUTO）。
- 任何失败都只记日志并跳过，绝不阻塞测试流水线；用户仍可走"手动上传报告"兜底。

依赖：worker 容器需挂载 Docker socket（docker.from_env() 可用），且 SUT 镜像内置
对应探针（Java 需 /opt/jacoco/jacocoagent.jar + jacococli.jar；Python 需 coverage）。
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Optional

from loguru import logger

from app.models.database import CoverageReport, CoverageSource, CoverageTool
from app.utils.database import AsyncSessionLocal
from app.modules.coverage.parser import parse_coverage_report


def _read_archive_stream(stream: Any) -> bytes:
    """docker-py get_archive 返回的第一元素：7.x 为 chunk 生成器，旧版为 BytesIO——统一读成 bytes。"""
    if hasattr(stream, "read"):
        return stream.read()
    return b"".join(chunk for chunk in stream)


def _extract_member(tar_bytes: bytes, suffix: str) -> Optional[str]:
    """从 docker archive tar 里提取指定后缀文件内容（文本）。"""
    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        for m in tar.getmembers():
            if m.name.endswith(suffix):
                f = tar.extractfile(m)
                if f:
                    return f.read().decode("utf-8", "ignore")
    return None


def override_command_for_coverage(image_cmd: list[str], language: str, tool: str) -> Optional[list[str]]:
    """
    根据 SUT 镜像原始启动命令，注入覆盖率探针，返回新命令。
    无法识别 / 不支持则返回 None（调用方降级为不上探针）。

    Python 探针自举（2026-08-30 修通自动采集的关键改造）：
    - 不再要求 SUT 镜像内置 coverage 包——启动时 `pip install coverage`（失败不阻塞，
      `|| true` 降级为无探针运行）；
    - COVERAGE_FILE 指到 /coverage 挂载卷，采集阶段 docker exec 生成 XML 后拷出；
    - 服务进程不会退出，XML 在采集阶段（collect_and_store）生成，不在此处拼接。
    """
    if not image_cmd:
        return None
    cmd = list(image_cmd)
    if language.startswith("java") or tool == "jacoco":
        # 找到 'java' 位置，在其后插入 javaagent
        # 注：JaCoCo 路径仍要求镜像内置 /opt/jacoco jar；平台公共卷挂载为后续增强
        for i, tok in enumerate(cmd):
            if os.path.basename(tok) == "java":
                agent = (
                    "-javaagent:/opt/jacoco/jacocoagent.jar="
                    "output=file,destfile=/coverage/jacoco.exec,includes=*"
                )
                cmd.insert(i + 1, agent)
                return cmd
        return None
    if language.startswith("python") or tool in ("coverage.py", "coverage.py", "coveragepy"):
        # coverage run 的参数是脚本/入口，不是解释器——
        # "coverage run python app.py" 会报 No file to run: '/app/python'（历史 bug，
        # 2026-08-30 实锤），python/python3 解释器本身必须剔除
        base = cmd[1:] if os.path.basename(cmd[0]).startswith("python") else cmd
        # 信号驱动采集（coverage.py 数据在进程退出时才落盘，长驻服务需外部触发优雅退出）。
        # 踩坑记录（全部 2026-08-30 实测）：
        #   1. "coverage run python app.py" → No file to run（解释器必须剔除）
        #   2. sh 后台 + trap 转发 INT → POSIX 规定非交互 shell 的后台子进程默认
        #      忽略 SIGINT，(trap - INT) 子 shell 也无法恢复（内核层面禁止）
        #   → 最终方案：sh exec 一个 Python 启动器作为容器主进程（PID1），
        #     subprocess.Popen(restore_signals=True) 会把子进程的 SIGINT 恢复为
        #     SIG_DFL（绕过 POSIX ignore 继承），coverage 进程因此能被 INT 优雅打断
        #     （KeyboardInterrupt → atexit 保存 .coverage）；启动器把 INT 转发给
        #     coverage 子进程，待其退出后生成 /coverage/coverage.xml 再退出（PID1
        #     已注册 handler，docker kill --signal=INT 对其生效）。
        launcher = (
            "import os, signal, subprocess, sys\n"
            "env = dict(os.environ, COVERAGE_FILE='/coverage/.coverage')\n"
            "p = subprocess.Popen(['coverage', 'run', '--source=.'] + sys.argv[1:], env=env)\n"
            "def _fwd(sig, frame):\n"
            "    if p.poll() is None:\n"
            "        p.send_signal(signal.SIGINT)\n"
            "signal.signal(signal.SIGINT, _fwd)\n"
            "p.wait()\n"
            "subprocess.run(['coverage', 'xml', '-i', '-o', '/coverage/coverage.xml'], env=env)\n"
        )
        wrapper = (
            "pip install coverage -q 2>/dev/null || true; exec python -c "
            + "'" + launcher.replace("'", "'\\''") + "' "
            + " ".join(base)
        )
        return [wrapper]
    return None


async def collect_and_store(
    test_run_id: str,
    meta: dict[str, Any],
    project_id: str,
) -> Optional[str]:
    """
    从已启动的 SUT 容器采集覆盖率并入库（source=AUTO）。
    成功返回报告 id；失败返回 None（不抛异常）。
    """
    container_id = meta.get("container_id")
    tool = meta.get("tool", "jacoco")
    language = meta.get("language", "java")
    if not container_id:
        return None
    try:
        import docker
        from docker.errors import NotFound

        client = docker.from_env()
        try:
            container = client.containers.get(container_id)
        except NotFound:
            logger.warning(f"[coverage] container {container_id} not found, skip auto-collect")
            return None

        # 从容器取出覆盖率数据
        with tempfile.TemporaryDirectory() as tmp:
            report_xml = None
            if tool == "jacoco":
                # 把 exec 拷出并尝试用 jacococli 转 xml；失败则提示手动上传
                exec_path = os.path.join(tmp, "jacoco.exec")
                try:
                    stream, _ = container.get_archive("/coverage/jacoco.exec")
                    exec_bytes = _read_archive_stream(stream)
                    with open(exec_path, "wb") as out:
                        out.write(exec_bytes)
                    # 用容器内 jacococli 生成 xml
                    container.exec_run(
                        "java -jar /opt/jacoco/jacococli.jar report /coverage/jacoco.exec "
                        f"--xml /coverage/jacoco.xml --sourcefiles /app",
                        privileged=False,
                    )
                    stream2, _ = container.get_archive("/coverage/jacoco.xml")
                    report_xml = _extract_member(_read_archive_stream(stream2), "jacoco.xml")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[coverage] JaCoCo extract failed: {e}")
            else:
                # Python coverage 信号驱动采集：
                #   SIGINT → 服务优雅退出 → atexit 保存 .coverage → wrapper 生成 XML
                #   → 容器主进程退出（exited 状态仍可 get_archive）→ 拷出 XML
                try:
                    import tarfile, io, time as _time

                    try:
                        container.kill(signal="INT")
                        logger.info("[coverage] SIGINT sent, waiting graceful exit + xml")
                    except Exception as e:  # noqa: BLE001 - 已退出/重试不影响后续
                        logger.info(f"[coverage] kill(INT) skipped: {e}")

                    for _ in range(20):  # 最多等 20 秒
                        _time.sleep(1)
                        try:
                            stream, _ = container.get_archive("/coverage/coverage.xml")
                            report_xml = _extract_member(
                                _read_archive_stream(stream), "coverage.xml"
                            )
                            if report_xml:
                                break
                        except Exception:
                            continue
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[coverage] coverage.py extract failed: {e}")

            # 采集收尾：显式删除 SUT 容器（auto_remove 已关闭）——
            # 解决容器无限堆积；删除失败仅告警
            try:
                container.remove(force=True)
                logger.info(f"[coverage] SUT container {container_id[:12]} removed after collect")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[coverage] SUT remove failed (non-fatal): {e}")

            if not report_xml:
                logger.warning("[coverage] no report produced; 请改用手动上传报告")
                return None

            result = parse_coverage_report(tool, report_xml)
            tool_enum = CoverageTool.JACOCO if tool == "jacoco" else CoverageTool.COBERTURA
            async with AsyncSessionLocal() as db:
                report = CoverageReport(
                    project_id=__import__("uuid").UUID(project_id),
                    test_run_id=__import__("uuid").UUID(test_run_id),
                    tool=tool_enum,
                    language=language,
                    source=CoverageSource.AUTO,
                    line_rate=result["line_rate"],
                    branch_rate=result["branch_rate"],
                    total_lines=result["total_lines"],
                    covered_lines=result["covered_lines"],
                    total_branches=result["total_branches"],
                    covered_branches=result["covered_branches"],
                    files_json=result["files"][:2000],
                )
                db.add(report)
                await db.commit()
                await db.refresh(report)
                logger.info(
                    f"[coverage] auto report stored {report.id}: "
                    f"line={result['line_rate']}% branch={result['branch_rate']}%"
                )
                return str(report.id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[coverage] auto-collect failed (fallback to upload): {e}")
        return None
    return None
