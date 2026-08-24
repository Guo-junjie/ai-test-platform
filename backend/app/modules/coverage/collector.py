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


def override_command_for_coverage(image_cmd: list[str], language: str, tool: str) -> Optional[list[str]]:
    """
    根据 SUT 镜像原始启动命令，注入覆盖率探针，返回新命令。
    无法识别 / 不支持则返回 None（调用方降级为不上探针）。
    """
    if not image_cmd:
        return None
    cmd = list(image_cmd)
    if language.startswith("java") or tool == "jacoco":
        # 找到 'java' 位置，在其后插入 javaagent
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
        # 用 coverage run 包裹：coverage run -m <module> 或 coverage run <script>
        if cmd and cmd[0].endswith("python") or cmd[0].endswith("python3"):
            return ["coverage", "run", "--source=."] + cmd[1:]
        # 形如 ['python','app.py'] → ['coverage','run','app.py']
        return ["coverage", "run", "--source=."] + cmd
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
                    bits = container.get_archive("/coverage/jacoco.exec")[0]
                    import tarfile, io

                    with tarfile.open(fileobj=io.BytesIO(bits.read())) as tar:
                        for m in tar.getmembers():
                            if m.name.endswith("jacoco.exec"):
                                f = tar.extractfile(m)
                                if f:
                                    with open(exec_path, "wb") as out:
                                        out.write(f.read())
                    # 用容器内 jacococli 生成 xml
                    container.exec_run(
                        "java -jar /opt/jacoco/jacococli.jar report /coverage/jacoco.exec "
                        f"--xml /coverage/jacoco.xml --sourcefiles /app",
                        privileged=False,
                    )
                    xml_bits = container.get_archive("/coverage/jacoco.xml")[0]
                    with tarfile.open(fileobj=io.BytesIO(xml_bits.read())) as tar:
                        for m in tar.getmembers():
                            if m.name.endswith("jacoco.xml"):
                                f = tar.extractfile(m)
                                if f:
                                    report_xml = f.read().decode("utf-8", "ignore")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[coverage] JaCoCo extract failed: {e}")
            else:
                # Python coverage：容器内执行 coverage xml 后拷贝
                try:
                    container.exec_run("coverage xml -o /coverage/coverage.xml", privileged=False)
                    import tarfile, io

                    xml_bits = container.get_archive("/coverage/coverage.xml")[0]
                    with tarfile.open(fileobj=io.BytesIO(xml_bits.read())) as tar:
                        for m in tar.getmembers():
                            if m.name.endswith("coverage.xml"):
                                f = tar.extractfile(m)
                                if f:
                                    report_xml = f.read().decode("utf-8", "ignore")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[coverage] coverage.py extract failed: {e}")

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
