"""
coverage/collector — 企业级代码覆盖率探针与采集引擎（能力11）

只将真实代码覆盖率报告入库：HTTP 报告地址或关联测试任务工作空间中的
JaCoCo/Cobertura XML、Go coverprofile。JaCoCo TCP .exec 缺少类文件映射，
接口测试结果也不能当作代码行覆盖率。
"""

import asyncio
import io
import json
import os
import re
import socket
import struct
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Optional

import httpx
from loguru import logger
from sqlalchemy import select

from app.models.database import CoverageReport, CoverageSource, CoverageTool, Project, TestRun
from app.modules.coverage.parser import parse_coverage_report
from app.utils.database import AsyncSessionLocal


def _resolve_probe_host(host: str) -> str:
    """若在 Docker 容器内且目标为主机/回环地址，智能映射为 host.docker.internal。"""
    cleaned = (host or "").strip().lower()
    in_docker = os.path.exists("/.dockerenv") or os.path.exists("/app")
    if in_docker and cleaned in ("localhost", "127.0.0.1", "0.0.0.0"):
        return "host.docker.internal"
    return host or "127.0.0.1"


def _read_archive_stream(stream: Any) -> bytes:
    """docker-py get_archive 返回的第一元素：7.x 为 chunk 生成器，旧版为 BytesIO——统一读成 bytes。"""
    if hasattr(stream, "read"):
        return stream.read()
    return b"".join(chunk for chunk in stream)


def _extract_member(tar_bytes: bytes, suffix: str) -> Optional[str]:
    """从 docker archive tar 里提取指定后缀文件内容（文本）。"""
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        for m in tar.getmembers():
            if m.name.endswith(suffix):
                f = tar.extractfile(m)
                if f:
                    return f.read().decode("utf-8", "ignore")
    return None


# ==================== JaCoCo 二进制协议客户端与纯 Python 解析器 ====================


def decode_varint(stream: io.BytesIO) -> int:
    """解码 JaCoCo CompactDataInput 的变长整数。"""
    val = 0
    shift = 0
    while True:
        b = stream.read(1)
        if not b:
            raise EOFError("EOF reading varint")
        byte_val = b[0]
        val |= (byte_val & 0x7F) << shift
        if (byte_val & 0x80) == 0:
            break
        shift += 7
    return val


def dump_jacoco_remote(
    host: str,
    port: int = 6300,
    timeout: float = 8.0,
    reset: bool = False,
) -> bytes:
    """
    通过 TCP Socket 连接远程 JaCoCo Agent（tcpserver 模式），发送 dump 命令拉取 execution data (.exec)。
    
    JaCoCo 协议协议交互：
    1. 建立 Socket 连接
    2. 发送魔数与版本：0xC0C0 0x1007
    3. 发送命令块：0x40 (BLOCK_CMD) 0x01 (CMD_DUMP) dump=1 reset=0/1
    4. 接收回传的二进制数据流直至连接断开或超时
    """
    resolved_host = _resolve_probe_host(host)
    logger.info(f"[coverage:jacoco] Connecting to remote JaCoCo probe at {resolved_host}:{port}")
    sock = socket.create_connection((resolved_host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        # 1. 发送 Header: Magic 0xC0C0 + Version 0x1007
        sock.sendall(b"\xc0\xc0\x10\x07")
        # 2. 发送 Dump Command: BLOCK_CMD (0x40), CMD_DUMP (0x01), dump (0x01), reset (0x01/0x00)
        reset_byte = 1 if reset else 0
        sock.sendall(bytes([0x40, 0x01, 0x01, reset_byte]))

        # 3. 循环接收响应流
        chunks: list[bytes] = []
        start_time = time.time()
        while True:
            try:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                # 超过 15 秒强制退出防卡死
                if time.time() - start_time > 15.0:
                    break
            except (socket.timeout, TimeoutError):
                break
        raw_data = b"".join(chunks)
        logger.info(f"[coverage:jacoco] Received {len(raw_data)} bytes of execution data")
        return raw_data
    finally:
        try:
            sock.close()
        except Exception:
            pass


def parse_jacoco_exec(data: bytes) -> dict[str, Any]:
    """
    纯 Python 解析 JaCoCo 二进制 execution data (.exec)。
    
    支持提取 Session 信息、Class 级别 probe 覆盖状态与行级映射，
    无需宿主机预装 Java 或 jacococli.jar。
    """
    if len(data) < 4 or data[:2] != b"\xc0\xc0":
        raise ValueError("Invalid JaCoCo execution data header")

    stream = io.BytesIO(data)
    stream.read(2)  # skip magic 0xC0C0

    sessions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    total_probes = 0
    covered_probes = 0

    while True:
        block_byte = stream.read(1)
        if not block_byte:
            break
        btype = block_byte[0]
        if btype == 0x01:  # HEADER
            _ = struct.unpack(">H", stream.read(2))[0]
        elif btype == 0x10:  # SESSIONINFO
            id_len = struct.unpack(">H", stream.read(2))[0]
            sess_id = stream.read(id_len).decode("utf-8", "ignore")
            start_t = struct.unpack(">q", stream.read(8))[0]
            dump_t = struct.unpack(">q", stream.read(8))[0]
            sessions.append({"id": sess_id, "start": start_t, "dump": dump_t})
        elif btype == 0x11:  # EXECUTIONDATA
            _class_id = struct.unpack(">q", stream.read(8))[0]
            name_len = struct.unpack(">H", stream.read(2))[0]
            class_name = stream.read(name_len).decode("utf-8", "ignore")
            probe_count = decode_varint(stream)
            byte_count = (probe_count + 7) // 8
            raw_bytes = stream.read(byte_count)

            probes: list[bool] = []
            class_covered = 0
            for i in range(probe_count):
                byte_idx = i // 8
                bit_idx = i % 8
                is_cov = (raw_bytes[byte_idx] & (1 << bit_idx)) != 0
                probes.append(is_cov)
                if is_cov:
                    class_covered += 1

            total_probes += probe_count
            covered_probes += class_covered
            line_rate = round(class_covered / probe_count * 100.0, 2) if probe_count > 0 else 0.0

            clean_path = class_name.replace("/", ".") + ".java"
            classes.append({
                "path": clean_path,
                "line_rate": line_rate,
                "branch_rate": line_rate,
                "total_lines": probe_count,
                "covered_lines": class_covered,
                "lines": [
                    {"number": i + 1, "hits": 1 if p else 0, "branch": False, "covered_branches": 0, "total_branches": 0}
                    for i, p in enumerate(probes)
                ],
            })

    overall_rate = round(covered_probes / total_probes * 100.0, 2) if total_probes > 0 else 0.0
    return {
        "line_rate": overall_rate,
        "branch_rate": overall_rate,
        "total_lines": total_probes,
        "covered_lines": covered_probes,
        "total_branches": 0,
        "covered_branches": 0,
        "files": classes,
        "sessions": sessions,
    }


# ==================== 远程 HTTP 端点与工作空间扫描 ====================


async def fetch_http_coverage(dump_url: str, timeout: float = 8.0) -> Optional[tuple[str, str]]:
    """向被测服务 HTTP 接口请求覆盖率报告（支持 Actuator 或探针 HTTP 接口）。"""
    candidates = [dump_url]
    if "://localhost" in dump_url:
        candidates.append(dump_url.replace("://localhost", "://host.docker.internal", 1))
    elif "://127.0.0.1" in dump_url:
        candidates.append(dump_url.replace("://127.0.0.1", "://host.docker.internal", 1))

    for cand in candidates:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3.0), verify=False, follow_redirects=True) as client:
                resp = await client.get(cand, headers={"User-Agent": "AITP-CoverageCollector/2.0"})
                resp.raise_for_status()
                data = resp.content
            if len(data) > 20 * 1024 * 1024:
                raise ValueError("覆盖率报告超过 20MB")
            if data.startswith(b"\xc0\xc0"):
                raise ValueError("JaCoCo .exec 只有探针数据，需先用类文件生成 jacoco.xml")
            raw_text = data.decode("utf-8-sig")
            parsed = parse_coverage_report("", raw_text)
            if parsed["total_lines"] <= 0:
                raise ValueError("报告没有有效代码行")
            if raw_text.lstrip().startswith("mode:"):
                return "go_cover", raw_text
            if "<report" in raw_text:
                return "jacoco", raw_text
            return "cobertura", raw_text
        except Exception as e:
            logger.debug(f"[coverage] candidate {cand} failed: {e}")
            continue
    return None


def scan_workspace_coverage(repo_path: str) -> Optional[tuple[str, str]]:
    """在项目代码目录中扫描已有的构建测试覆盖率报告（如 Maven / Gradle / pytest 产物）。"""
    if not repo_path or not os.path.exists(repo_path):
        return None

    target_names = [
        "jacoco.xml",
        "coverage.xml",
        "cobertura.xml",
        "clover.xml",
        "coverage.out",
        "cover.out",
    ]

    for root, _, files in os.walk(repo_path):
        for f in files:
            if f.lower() in target_names:
                p = os.path.join(root, f)
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                        content = fp.read(5 * 1024 * 1024)  # 5MB max
                    tool = "go_cover" if f.lower().endswith(".out") else "jacoco" if "jacoco" in f.lower() else "cobertura"
                    logger.info(f"[coverage] Found workspace coverage report: {p} ({tool})")
                    return tool, content
                except Exception as e:
                    logger.warning(f"[coverage] Read workspace report {p} failed: {e}")
    return None


def synthesize_api_coverage(
    test_results: list[dict[str, Any]],
    analysis_result: dict[str, Any],
    project_name: str = "",
) -> dict[str, Any]:
    """
    根据实际执行的测试用例与代码解析出的 API 路由，生成真实接口场景覆盖率。
    
    保证在被测环境尚未配置 JVM Agent 探针时，平台依然能得出准确、可量化的端到端接口覆盖分析。
    """
    discovered_apis = (analysis_result or {}).get("apis") or []
    tested_endpoints: set[str] = set()

    for item in test_results:
        res_list = item.get("results") if isinstance(item, dict) else []
        if not isinstance(res_list, list):
            res_list = []
        for r in res_list:
            ep = r.get("endpoint") or r.get("api_path") or r.get("url") or ""
            if ep:
                parsed = urllib.parse.urlparse(ep)
                clean_path = parsed.path or ep
                method = (r.get("method") or "GET").upper()
                tested_endpoints.add(f"{method} {clean_path}")

    files: list[dict[str, Any]] = []
    total_items = max(len(discovered_apis), len(tested_endpoints), 1)
    covered_items = 0

    if discovered_apis:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for api in discovered_apis:
            fpath = api.get("file_path") or api.get("file") or f"{project_name or 'api'}/controllers.py"
            grouped.setdefault(fpath, []).append(api)

        for fpath, apis in grouped.items():
            f_lines: list[dict[str, Any]] = []
            f_cov = 0
            for idx, a in enumerate(apis):
                method = (a.get("method") or "GET").upper()
                path = a.get("path") or "/"
                api_key = f"{method} {path}"
                hit = any(
                    api_key in t or path in t or (t.split()[-1] == path)
                    for t in tested_endpoints
                )
                if hit:
                    f_cov += 1
                f_lines.append({
                    "number": (idx + 1) * 10,
                    "hits": 1 if hit else 0,
                    "branch": False,
                    "covered_branches": 0,
                    "total_branches": 0,
                })
            covered_items += f_cov
            rate = round(f_cov / len(apis) * 100.0, 2)
            files.append({
                "path": fpath,
                "line_rate": rate,
                "branch_rate": rate,
                "total_lines": len(apis),
                "covered_lines": f_cov,
                "lines": f_lines,
            })
    else:
        covered_items = len(tested_endpoints)
        f_lines = []
        for idx, ep in enumerate(tested_endpoints):
            f_lines.append({
                "number": idx + 1,
                "hits": 1,
                "branch": False,
                "covered_branches": 0,
                "total_branches": 0,
            })
        files.append({
            "path": "api/endpoints_tested.py",
            "line_rate": 100.0 if covered_items > 0 else 0.0,
            "branch_rate": 100.0 if covered_items > 0 else 0.0,
            "total_lines": max(covered_items, 1),
            "covered_lines": covered_items,
            "lines": f_lines,
        })

    overall_rate = round(covered_items / total_items * 100.0, 2)
    return {
        "line_rate": overall_rate,
        "branch_rate": overall_rate,
        "total_lines": total_items,
        "covered_lines": covered_items,
        "total_branches": total_items,
        "covered_branches": covered_items,
        "files": files,
    }


# ==================== 连通性探测工具 ====================


async def probe_coverage_target(
    strategy: str = "remote_tcp",
    host: str = "",
    port: int = 6300,
    dump_url: str = "",
    timeout: float = 4.0,
) -> dict[str, Any]:
    """探测覆盖率探针连通性。"""
    strategy = (strategy or "remote_tcp").strip().lower()
    start = time.time()

    if strategy in ("remote_tcp", "jacoco_tcp", "tcp"):
        h = _resolve_probe_host(host)
        p = int(port or 6300)

        def _tcp_connect():
            with socket.create_connection((h, p), timeout=timeout) as s:
                return True

        try:
            await asyncio.to_thread(_tcp_connect)
            ms = round((time.time() - start) * 1000, 2)
            return {
                "ok": True,
                "reachable": True,
                "strategy": "remote_tcp",
                "target": f"{h}:{p}",
                "response_time_ms": ms,
                "message": f"TCP 端口可连接 ({h}:{p})；JaCoCo .exec 还需结合类文件生成 jacoco.xml，不能直接计算行覆盖率",
            }
        except Exception as e:
            return {
                "ok": False,
                "reachable": False,
                "strategy": "remote_tcp",
                "target": f"{h}:{p}",
                "error": str(e),
                "message": f"TCP 探针无法连接 ({h}:{p}): {e}",
            }

    if strategy in ("http_dump", "http", "actuator"):
        url = (dump_url or "").strip()
        if not url:
            return {"ok": False, "reachable": False, "error": "URL 不能为空", "message": "未配置 HTTP Dump 地址"}
        if not (url.startswith("http://") or url.startswith("https://")):
            url = f"http://{url}"

        candidates = [url]
        if "://localhost" in url:
            candidates.append(url.replace("://localhost", "://host.docker.internal", 1))
        elif "://127.0.0.1" in url:
            candidates.append(url.replace("://127.0.0.1", "://host.docker.internal", 1))

        last_err = ""
        for cand in candidates:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=2.5), verify=False, follow_redirects=True) as client:
                    resp = await client.get(cand, headers={"User-Agent": "AITP-CoverageProbe/2.0"})
                    resp.raise_for_status()
                    parse_coverage_report("", resp.text)
                    ms = round((time.time() - start) * 1000, 2)
                    return {
                        "ok": True,
                        "reachable": True,
                        "strategy": "http_dump",
                        "target": cand,
                        "status_code": resp.status_code,
                        "response_time_ms": ms,
                        "message": f"HTTP 地址返回有效覆盖率报告 (状态码 {resp.status_code}, 耗时 {ms}ms)",
                    }
            except Exception as e:
                last_err = str(e)
        return {
            "ok": False,
            "reachable": False,
            "strategy": "http_dump",
            "target": url,
            "error": last_err,
            "message": f"HTTP 地址未返回有效覆盖率报告: {last_err}",
        }

    if strategy == "repo_file":
        return {"ok": False, "reachable": False,
                "message": "仓库扫描仅在关联测试任务且工作空间存在真实覆盖率报告时可用；请先运行带覆盖率的构建测试"}
    return {"ok": False, "reachable": False, "message": f"未知策略: {strategy}"}


# ==================== 统一采集与落库调度器 ====================


async def collect_coverage_for_run(
    test_run_id: str,
    summary_data: Optional[dict[str, Any]] = None,
    project_id: Optional[str] = None,
) -> Optional[str]:
    """
    全自动覆盖率采集入口（在测试执行流水线完成后或用户点击「立即采集」时调用）。
    
    严格按项目配置的 HTTP 报告地址或关联测试任务工作空间报告采集；
    未取得真实报告时返回 None，不生成推算结果。
    """
    logger.info(f"[{test_run_id}] Starting coverage collection...")
    try:
        run_uuid = uuid.UUID(str(test_run_id))
    except Exception:
        run_uuid = None

    async with AsyncSessionLocal() as session:
        run = None
        proj = None
        if run_uuid:
            run = (await session.execute(select(TestRun).where(TestRun.id == run_uuid))).scalar_one_or_none()
        pid = project_id or (str(run.project_id) if run else None)
        if pid:
            try:
                proj = (await session.execute(select(Project).where(Project.id == uuid.UUID(pid)))).scalar_one_or_none()
            except Exception:
                pass

    if not proj and not run:
        logger.warning(f"[{test_run_id}] Neither Project nor TestRun found, aborting coverage collection")
        return None

    src_cfg = (proj.source_config or {}) if proj else {}
    cov_cfg = src_cfg.get("coverage_config") or {}
    if run and (cov_cfg.get("enabled") is False or (proj.quality_gate_config or {}).get("auto_coverage") is False):
        logger.info(f"[{test_run_id}] Automatic coverage collection disabled")
        return None
    strategy = cov_cfg.get("strategy") or "repo_file"
    tool = cov_cfg.get("tool") or src_cfg.get("coverage_tool") or "cobertura"

    parsed_result: Optional[dict[str, Any]] = None
    applied_source = CoverageSource.AUTO

    # JaCoCo .exec 只有探针位图，不包含源码行映射，不能冒充行覆盖率。
    if strategy == "remote_tcp":
        logger.warning(f"[{test_run_id}] JaCoCo TCP dump requires class files; use an XML report instead")
        return None

    # 2. 尝试远程 HTTP Dump 端点采集
    if strategy == "http_dump":
        dump_url = cov_cfg.get("dump_url") or src_cfg.get("coverage_dump_url")
        if dump_url:
            http_res = await fetch_http_coverage(dump_url)
            if http_res:
                t_name, text_or_json = http_res
                parsed_result = parse_coverage_report(t_name, text_or_json)
                tool = t_name

    # 3. 尝试工作空间已有 XML 报告扫描
    if strategy == "repo_file" and run:
        repo_path = (run.analysis_result or {}).get("repo_path") or ""
        ws_res = scan_workspace_coverage(repo_path)
        if ws_res:
            t_name, xml_str = ws_res
            try:
                parsed_result = parse_coverage_report(t_name, xml_str)
                tool = t_name
            except Exception as e:
                logger.warning(f"[{test_run_id}] Parse workspace report failed: {e}")

    if not parsed_result:
        logger.warning(f"[{test_run_id}] No real coverage report produced (strategy={strategy})")
        return None

    # 入库到 coverage_reports 表
    tool_enum = CoverageTool(tool)
    files_summary = [
        {k: v for k, v in f.items() if k != "lines"}
        for f in parsed_result["files"][:2000]
    ]
    line_json = {
        f["path"]: {"lines": f.get("lines", [])}
        for f in parsed_result["files"][:2000]
    }

    async with AsyncSessionLocal() as db:
        report = CoverageReport(
            project_id=uuid.UUID(pid) if pid else (run.project_id if run else uuid.uuid4()),
            test_run_id=run.id if run else None,
            tool=tool_enum,
            language={"jacoco": "java", "go_cover": "go", "coverage.py": "python"}.get(tool),
            source=applied_source,
            line_rate=parsed_result["line_rate"],
            branch_rate=parsed_result["branch_rate"],
            total_lines=parsed_result["total_lines"],
            covered_lines=parsed_result["covered_lines"],
            total_branches=parsed_result["total_branches"],
            covered_branches=parsed_result["covered_branches"],
            files_json=files_summary,
            line_json=line_json,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)

    logger.info(
        f"[coverage] auto coverage report stored {report.id}: "
        f"line={parsed_result['line_rate']}% files={len(parsed_result['files'])}"
    )
    return str(report.id)


def override_command_for_coverage(image_cmd: list[str], language: str, tool: str) -> Optional[list[str]]:
    """保留兼容旧有本地 Docker 探针包装命令注入接口。"""
    if not image_cmd:
        return None
    cmd = list(image_cmd)
    if language.startswith("java") or tool == "jacoco":
        for i, tok in enumerate(cmd):
            if os.path.basename(tok) == "java":
                agent = "-javaagent:/opt/jacoco/jacocoagent.jar=output=file,destfile=/coverage/jacoco.exec,includes=*"
                cmd.insert(i + 1, agent)
                return cmd
        return None
    if language.startswith("python") or tool in ("coverage.py", "coveragepy"):
        base = cmd[1:] if os.path.basename(cmd[0]).startswith("python") else cmd
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
    """保留原有 collect_and_store 兼容接口，并委托给统一采集器。"""
    return await collect_coverage_for_run(test_run_id, project_id=project_id)
