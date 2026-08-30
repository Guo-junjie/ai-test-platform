"""覆盖率探针注入命令测试（能力11 自动采集的启动端，纯函数无 IO）。

回归背景：2026-08-30 修通自动覆盖率——原实现要求 SUT 镜像内置 coverage 包
（三重前提不满足导致链路从未跑通），改为启动时 pip 自举 + COVERAGE_FILE 指向挂载卷。
"""
from app.modules.coverage.collector import override_command_for_coverage


class TestPythonBootstrap:
    def test_python_script_launcher(self):
        """解释器剔除 + pip 自举 + Python 启动器信号驱动（数据退出落盘 → xml 生成）。"""
        out = override_command_for_coverage(["python", "app.py"], "python", "coverage.py")
        assert out is not None and len(out) == 1
        cmd = out[0]
        assert "pip install coverage" in cmd
        assert "|| true" in cmd  # 无外网降级：装不上也照常启动
        assert "exec python -c" in cmd           # 启动器作为容器主进程（PID1）
        assert "p.send_signal(signal.SIGINT)" in cmd  # INT 转发给 coverage 子进程
        assert "/coverage/coverage.xml" in cmd   # 退出后生成 XML（经 sh 转义）
        # /coverage 挂载卷路径出现两次：run 数据文件 + xml 输出
        assert cmd.count("/coverage") >= 2
        # 回归锁（2026-08-30 实测）：Popen 漏传 env → 数据写到 /app 而非挂载卷
        assert "env=env)" in cmd

    def test_interpreter_stripped(self):
        """python/python3 解释器本身不得进入 coverage run 参数（历史 bug 回归锁）。"""
        out = override_command_for_coverage(["python", "app.py"], "python", "coverage.py")
        assert " python app.py" not in out[0]
        out3 = override_command_for_coverage(["python3", "main.py"], "python", "coverage.py")
        assert " python3 main.py" not in out3[0]
        assert out3[0].rstrip().endswith("main.py")

    def test_uvicorn_entry_kept(self):
        """非解释器入口（uvicorn 等 console script）保留原样传给启动器。"""
        out = override_command_for_coverage(["uvicorn", "main:app"], "python", "coverage.py")
        assert out is not None
        assert "uvicorn main:app" in out[0]


class TestJavaAgent:
    def test_java_agent_inserted_after_java(self):
        out = override_command_for_coverage(
            ["java", "-jar", "app.jar"], "java", "jacoco"
        )
        assert out == [
            "java",
            "-javaagent:/opt/jacoco/jacocoagent.jar=output=file,"
            "destfile=/coverage/jacoco.exec,includes=*",
            "-jar",
            "app.jar",
        ]

    def test_no_java_token_returns_none(self):
        assert override_command_for_coverage(["notjava", "-jar", "x"], "java", "jacoco") is None


class TestFallbacks:
    def test_empty_cmd_returns_none(self):
        assert override_command_for_coverage([], "python", "coverage.py") is None

    def test_unknown_language_returns_none(self):
        assert override_command_for_coverage(["node", "app.js"], "node", "cobertura") is None
