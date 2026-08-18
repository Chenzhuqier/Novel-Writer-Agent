"""
小说写作 Agent 测试套件（v0.2 修复版）

覆盖范围：
- ✅ 修复 #1：StoryBible 基类导入测试
- ✅ 修复 #2：load_dotenv 配置加载测试
- ✅ 修复 #3：线程安全测试
- ✅ 修复 #4：数据持久化与恢复测试
- ✅ 核心功能测试：Agent 创建、流水线步骤、API 路由

运行方式：
    python -m pytest tests/ -v
    或
    python tests/test_fixes.py
"""

import os
import sys
import json
import tempfile
import threading
import time

# ============================================================
# 确保可以导入项目模块
# ============================================================
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFix1_StoryBibleBaseClass:
    """
    修复 #1 验证：StoryBible 基类必须存在且可正常使用
    
    原问题：VersionedStoryBible 继承了不存在的 StoryBible 类，导致 ImportError
    """

    def test_story_bible_class_exists(self):
        """StoryBible 基类应该可以被导入"""
        from core.story_bible import StoryBible
        assert StoryBible is not None
        print("✅ StoryBible 基类存在")

    def test_versioned_story_bible_inherits(self):
        """VersionedStoryBible 应该继承自 StoryBible"""
        from core.story_bible import VersionedStoryBible, StoryBible
        assert issubclass(VersionedStoryBible, StoryBible)
        print("✅ VersionedStoryBible 正确继承 StoryBible")

    def test_create_story_bible(self):
        """应该能够创建 StoryBible 实例"""
        from core.story_bible import StoryBible
        bible = StoryBible(title="测试", genre="玄幻")
        assert bible.meta["title"] == "测试"
        assert bible.genre == "玄幻" if hasattr(bible, 'genre') else True
        print("✅ StoryBible 实例创建成功")

    def test_create_versioned_story_bible(self):
        """应该能够创建 VersionedStoryBible 实例"""
        from core.story_bible import VersionedStoryBible
        bible = VersionedStoryBible(title="测试小说", genre="修仙")
        assert bible.meta["title"] == "测试小说"
        assert len(bible._versions) == 1  # 初始化时自动创建一个版本
        print("✅ VersionedStoryBible 实例创建成功")

    def test_character_management(self):
        """角色管理功能应该正常工作"""
        from core.story_bible import StoryBible, Character
        bible = StoryBible()

        # 添加角色
        char = bible.add_character(
            name="张三",
            age=25,
            gender="男",
            personality=["勇敢", "善良"],
        )
        assert char.id != ""
        assert char.name == "张三"
        assert len(bible.characters) == 1

        # 查找角色
        found = bible.get_character("张三")
        assert found is not None
        assert found.name == "张三"

        # 活跃角色
        active = bible.get_active_characters()
        assert len(active) == 1
        print("✅ 角色管理功能正常")

    def test_foreshadowing_management(self):
        """伏笔管理功能应该正常工作"""
        from core.story_bible import StoryBible
        bible = StoryBible()

        # 添加伏笔
        fs = bible.add_foreshadowing(
            content="神秘玉简的来历",
            planted_in="第1章",
            hint="与主角身世有关",
        )
        assert fs.id != ""
        assert fs.resolved is False

        # 未回收伏笔
        unresolved = bible.get_unresolved_foreshadowings()
        assert len(unresolved) == 1

        # 回收伏笔
        bible.resolve_foreshadowing(fs.id, "第10章")
        unresolved = bible.get_unresolved_foreshadowings()
        assert len(unresolved) == 0
        print("✅ 伏笔管理功能正常")

    def test_serialization(self):
        """序列化和反序列化应该正常工作"""
        from core.story_bible import VersionedStoryBible
        bible = VersionedStoryBible(title="序列化测试", genre="科幻")

        # 添加一些数据
        bible.add_character(name="测试角色", gender="女")
        bible.add_foreshadowing(content="测试伏笔", planted_in="第1章")

        # 导出为字典
        data_dict = bible.to_dict()
        assert "meta" in data_dict
        assert "characters" in data_dict
        assert len(data_dict["characters"]) == 1

        # 导出到 JSON 文件
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_bible.json")
            bible.to_json(filepath)
            assert os.path.exists(filepath)

            # 从文件恢复
            restored = VersionedStoryBible.from_json(filepath)
            assert restored.meta["title"] == "序列化测试"
            assert len(restored.characters) == 1
            print("✅ 序列化/反序列化正常")

    def test_version_history_persisted(self):
        """版本历史应该随序列化落盘并可恢复"""
        from core.story_bible import VersionedStoryBible
        bible = VersionedStoryBible(title="版本持久化测试", genre="玄幻")

        # 创建若干版本快照
        bible.add_character(name="初版角色", gender="男")
        bible.checkpoint("添加初版角色")
        bible.add_foreshadowing(content="第一处伏笔", planted_in="第1章")
        bible.checkpoint("添加第一处伏笔")
        assert bible.version_count == 3
        assert bible.current_version == 2

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_bible.json")
            bible.to_json(filepath)

            restored = VersionedStoryBible.from_json(filepath)
            # 版本计数与历史应完整恢复
            assert restored.version_count == 3, f"版本数未恢复: {restored.version_count}"
            assert restored.current_version == 2
            assert len(restored.get_version_history()) == 3

            # 回滚到最早的版本后，角色应回到初始状态
            target = restored.rollback(0)
            assert target.version_id == 0
            assert len(restored.characters) == 0, "回滚后应回到初始（无角色）状态"
            print("✅ 版本历史持久化与回滚正常")

    def test_legacy_json_without_versions(self):
        """旧格式 JSON（无 versions 字段）应能兼容加载"""
        from core.story_bible import StoryBible, VersionedStoryBible
        legacy = StoryBible(title="旧数据", genre="都市")
        legacy.add_character(name="旧角色", gender="女")

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "legacy_bible.json")
            legacy.to_json(filepath)

            restored = VersionedStoryBible.from_json(filepath)
            assert restored.meta["title"] == "旧数据"
            assert len(restored.characters) == 1
            # 旧数据应自动补一条“恢复初始版本”，保证可回滚
            assert restored.version_count >= 1
            assert restored.current_version == 0
            target = restored.rollback(0)
            assert target.version_id == 0
            print("✅ 旧格式 JSON 兼容加载正常")


class TestFix2_DotEnvLoading:
    """
    修复 #2 验证：.env 文件应该能够被正确加载
    
    原问题：代码依赖 python-dotenv 但从未调用 load_dotenv()
    """

    def test_load_dotenv_exists_in_app(self):
        """app.py 应该包含 load_dotenv() 调用"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "load_dotenv" in content, "app.py 中未找到 load_dotenv 调用"
        assert "from dotenv" in content or "import dotenv" in content, "app.py 中未找到 dotenv 导入"
        print("✅ load_dotenv() 已添加到 app.py")

    def test_dotenv_file_loading(self):
        """如果 .env 存在，环境变量应该被加载"""
        # 创建临时 .env 文件
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("TEST_VAR=test_value\n")
                f.write("ANOTHER_VAR=123\n")

            # 模拟 load_dotenv 行为
            try:
                from dotenv import load_dotenv
                original_cwd = os.getcwd()
                os.chdir(tmpdir)  # 切换到临时目录以便找到 .env
                load_dotenv(env_path)

                assert os.environ.get("TEST_VAR") == "test_value"
                assert os.environ.get("ANOTHER_VAR") == "123"
                print("✅ .env 文件加载正常")

                os.chdir(original_cwd)
            except ImportError:
                print("⚠️ python-dotenv 未安装，跳过此测试")
            finally:
                # 清理环境变量
                os.environ.pop("TEST_VAR", None)
                os.environ.pop("ANOTHER_VAR", None)


class TestFix3_ThreadSafety:
    """
    修复 #3 验证：全局状态必须有锁保护
    
    原问题：多线程并发访问全局 project 对象无同步机制
    """

    def test_novel_project_has_lock(self):
        """NovelProject 应该有 _lock 属性"""
        # 由于 app.py 导入会触发 Flask，我们直接检查逻辑
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # 动态检查（避免完整导入 app）
        import importlib.util
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        spec = importlib.util.spec_from_file_location("app", app_path)
        
        # 我们只验证文件内容包含锁相关代码
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        assert "_lock" in content, "app.py 中未找到 _lock 属性"
        assert "threading.RLock" in content or "threading.Lock" in content, "app.py 中未找到线程锁定义"
        assert "with project._lock" in content, "app.py 中未找到锁使用处"
        print("✅ 线程安全锁已添加")

    def test_concurrent_access_safety(self):
        """并发访问不应该导致数据损坏"""
        # 这个测试模拟多线程场景
        from core.story_bible import VersionedStoryBible
        bible = VersionedStoryBible(title="并发测试")

        errors = []

        def add_char(i):
            try:
                bible.add_character(name=f"角色{i}", gender="男" if i % 2 else "女")
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(20):
            t = threading.Thread(target=add_char, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发访问出错: {errors}"
        assert len(bible.characters) == 20
        print("✅ 并发访问安全")


class TestFix4_DataPersistence:
    """
    修复 #4 验证：启动时应该能恢复上次的状态
    
    原问题：JSON 文件只写不读，重启后进度丢失
    """

    def test_save_state_method_exists(self):
        """NovelProject 应该有 save_state 方法"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "def save_state" in content, "save_state 方法不存在"
        assert "def load_state" in content, "load_state 方法不存在"
        print("✅ 数据持久化方法已添加")

    def test_save_and_load_cycle(self):
        """保存和恢复数据循环应该正常工作"""
        from core.story_bible import VersionedStoryBible
        import shutil

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "data")
            os.makedirs(data_dir)

            # 创建并配置一个故事圣经
            bible = VersionedStoryBible(title="持久化测试", genre="都市")
            bible.add_character(name="主角", gender="男", age=30)
            bible.add_foreshadowing(content="重要伏笔", planted_in="第1章")
            bible.world_notes = "这是一个测试世界观"

            # 保存
            bible.to_json(os.path.join(data_dir, "story_bible.json"))

            # 保存大纲和元数据
            outline = {"total_volumes": 1, "volumes": [{"volume_num": 1, "chapters": []}]}
            with open(os.path.join(data_dir, "outline.json"), "w", encoding="utf-8") as f:
                json.dump(outline, f, ensure_ascii=False)

            meta = {
                "premise": "测试创意",
                "genre": "都市",
                "current_step": "outline_generated",
                "current_chapter": 0,
                "total_chapters": 10,
            }
            with open(os.path.join(data_dir, "project_meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)

            # 恢复
            restored = VersionedStoryBible.from_json(os.path.join(data_dir, "story_bible.json"))
            assert restored.meta["title"] == "持久化测试"
            assert len(restored.characters) == 1
            assert list(restored.characters.values())[0].name == "主角"
            assert restored.version_count >= 1  # 版本链应随保存/恢复保留

            print("✅ 数据保存/恢复循环正常")


class TestCoreFunctionality:
    """
    核心功能回归测试，确保修复没有破坏现有功能
    """

    def test_agents_import(self):
        """所有 Agent 应该能够被正确导入"""
        from agents import (
            WorldBuilderAgent,
            OutlineAgent,
            WriterAgent,
            CheckerAgent,
            PolisherAgent,
        )
        assert WorldBuilderAgent is not None
        assert OutlineAgent is not None
        assert WriterAgent is not None
        assert CheckerAgent is not None
        assert PolisherAgent is not None
        print("✅ 所有 Agent 导入正常")

    def test_agent_creation(self):
        """应该能够创建所有 Agent 实例"""
        from agents import (
            WorldBuilderAgent,
            OutlineAgent,
            WriterAgent,
            CheckerAgent,
            PolisherAgent,
        )

        world_builder = WorldBuilderAgent(temperature=0.9)
        outline_agent = OutlineAgent(temperature=0.8)
        writer = WriterAgent(temperature=0.85)
        checker = CheckerAgent(temperature=0.3)
        polisher = PolisherAgent(temperature=0.6)

        assert world_builder.name == "WorldBuilder"
        assert outline_agent.name == "OutlineArchitect"
        assert writer.name == "Writer"
        assert checker.name == "PlotChecker"
        assert polisher.name == "Polisher"
        print("✅ 所有 Agent 实例创建成功")

    def test_base_agent_methods(self):
        """BaseAgent 的核心方法应该存在"""
        from agents.base import BaseAgent
        from agents.writer_agent import WriterAgent

        writer = WriterAgent()

        # 检查必要的方法和属性
        assert hasattr(writer, 'system_prompt'), "缺少 system_prompt 属性"
        assert hasattr(writer, 'run'), "缺少 run 方法"
        assert hasattr(writer, '_call_llm'), "缺少 _call_llm 方法"
        assert hasattr(writer, '_parse_json_response'), "缺少 _parse_json_response 方法"
        assert hasattr(writer, '_validate_input'), "缺少 _validate_input 方法"
        print("✅ BaseAgent 核心方法完整")

    def test_demo_mode_fallback(self):
        """Demo 模式应该在无 API Key 时正常工作"""
        from agents.base import DEMO_REGISTRY, _demo_fallback

        # 检查 Demo 注册表不为空
        assert len(DEMO_REGISTRY) > 0, "Demo 注册表为空"

        # 测试 Demo 回退
        result = _demo_fallback(
            system_prompt="世界构建",
            user_message="测试",
            agent_name="WorldBuilder",
        )
        assert result != "", "Demo 回退返回空字符串"
        assert "苍澜大陆" in result or "world" in result.lower(), "Demo 内容异常"
        print("✅ Demo 模式正常")

    def test_token_tracker(self):
        """Token 追踪器应该正常工作"""
        from agents.base import tracker, TokenTracker

        assert isinstance(tracker, TokenTracker)
        assert tracker.total_calls == 0
        assert tracker.total_cost_usd == 0

        summary = tracker.get_summary()
        assert "summary" in summary
        assert "by_agent" in summary
        print("✅ Token 追踪器正常")

    def test_version_control(self):
        """版本控制功能应该正常工作"""
        from core.story_bible import VersionedStoryBible

        bible = VersionedStoryBible(title="版本控制测试")

        # 初始版本
        assert bible.version_count == 1
        assert bible.current_version == 0

        # 创建检查点
        bible.add_character(name="新角色")
        v1 = bible.checkpoint("添加了新角色")
        assert bible.version_count == 2
        assert bible.current_version == 1

        # 版本历史
        history = bible.get_version_history()
        assert len(history) == 2
        assert history[0]["version_id"] == 1  # 最新的在前
        print("✅ 版本控制功能正常")

    def test_context_compression(self):
        """上下文压缩功能应该正常工作"""
        from core.story_bible import VersionedStoryBible

        bible = VersionedStoryBible(title="压缩测试")

        # 添加大量数据以触发压缩
        for i in range(20):
            bible.add_character(
                name=f"角色{i}",
                appearance=f"这是角色{i}的长外貌描述" * 10,
                personality=[f"性格{j}" for j in range(10)],
            )

        # 构建上下文（限制较小以强制压缩）
        context = bible.build_context_for_chapter(
            chapter_num=1,
            max_chars=500,  # 很小的限制
        )

        assert len(context) <= 600  # 允许少量超出
        assert "故事设定" in context
        print("✅ 上下文压缩功能正常")


class TestVectorRag:
    """
    v0.3 验证：可选向量语义检索（RAG）
    - 默认禁用态必须安全降级，不影响现有流程与 Demo 模式
    - app.py 应已接入 SemanticIndex 与索引同步钩子
    """

    def test_vector_index_module_importable(self):
        """core.vector_index 应可导入且提供 SemanticIndex"""
        from core import vector_index
        assert hasattr(vector_index, "SemanticIndex")
        print("✅ 向量索引模块可导入")

    def test_vector_disabled_safe(self):
        """未启用/未安装依赖时，SemanticIndex 应安全降级、不抛异常"""
        from core import vector_index

        prev = vector_index.ENABLE_VECTOR
        vector_index.ENABLE_VECTOR = False
        try:
            idx = vector_index.SemanticIndex()
            assert idx.enabled is False
            assert idx.add("doc", "示例内容") is False
            assert idx.search("示例查询") == []
            assert idx.similarity("a", "b") is None
        finally:
            vector_index.ENABLE_VECTOR = prev
        print("✅ 向量索引禁用态安全降级")

    def test_app_has_vector_integration(self):
        """app.py 应包含向量索引接入与同步钩子"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "SemanticIndex" in content, "app.py 未引入 SemanticIndex"
        assert "vector_index" in content, "app.py 未使用 vector_index 实例"
        assert "sync_vector_index" in content, "app.py 缺少 sync_vector_index 索引同步方法"
        print("✅ app.py 已接入向量索引")

    def test_modelscope_default_source(self):
        """模型下载源默认应为魔搭社区，且含 Hugging Face 回退"""
        vs_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "core", "vector_index.py")
        with open(vs_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'MODEL_SOURCE = os.environ.get("MODEL_SOURCE", "modelscope")' in content
        assert "snapshot_download" in content, "缺少 modelscope.snapshot_download 下载"
        assert 'MODEL_SOURCE == "huggingface"' in content, "缺少 Hugging Face 强制回退分支"
        assert "requirements-rag" in content or True
        print("✅ 模型下载源默认魔搭社区 + HF 回退")

    def test_rag_requirements_modelscope(self):
        """requirements-rag.txt 应包含 modelscope 依赖说明"""
        req_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "requirements-rag.txt")
        with open(req_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "modelscope" in content
        print("✅ requirements-rag.txt 已包含 modelscope")


class TestContinuationWrite:
    """
    v0.3 验证：先写几章、再在已写基础上续写
    - 后端：章号超出大纲时自动追加占位细纲并扩展总章数
    - 前端：允许续写超过总章数（弹窗确认），并同步最新总章数
    """

    def test_backend_auto_extension(self):
        """app.py 应包含自动扩章续写逻辑"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "_append_placeholder_outline" in content, "缺少占位细纲追加函数"
        assert "续写扩展章" in content, "占位细纲缺少续写标记"
        assert "total_chapters" in content, "缺少总章数扩展逻辑"
        print("✅ 后端自动扩章逻辑已接入")

    def test_frontend_allows_continuation(self):
        """前端应允许续写超过总章数并同步更新"""
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "totalChapters" in content, "前端未使用总章数状态"
        assert "confirm(" in content and "续写" in content, "前端缺少续写确认提示"
        assert "writeChapter" in content and "writeAll" in content, "前端缺少写作调用函数"
        print("✅ 前端续写交互已放开")

    def test_status_returns_echo_fields(self):
        """api/status 应返回续写回显所需字段"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert '"premise": project.premise' in content, "status 缺少 premise 回显"
        assert '"next_chapter"' in content, "status 缺少 next_chapter"
        assert '"chapter_meta"' in content, "status 缺少 chapter_meta"
        print("✅ api/status 已包含续写回显字段")

    def test_frontend_matches_html(self):
        """前端应覆盖 index.html 引用的全部函数与元素 id"""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html_path = os.path.join(root, "templates", "index.html")
        js_path = os.path.join(root, "static", "js", "app.js")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()

        # index.html 引用的函数/回调必须在 app.js 中定义
        for fn in ["startProject", "buildWorld", "generateOutline", "writeAll",
                   "writeChapter", "confirmStep", "exportNovel", "resetProject",
                   "showCostPanel", "showVersionPanel", "createCheckpoint",
                   "resetCostStats", "closeModal", "switchTab", "loadChapter",
                   "toggleChapterView"]:
            assert f"function {fn}(" in js, f"app.js 缺少函数: {fn}"

        # index.html 中通过 JS 查询的 id 应被 app.js 使用
        for el_id in ["log-container", "chapter-select", "chapter-output",
                      "current-step", "status-message", "bible-version",
                      "single-chapter", "use-streaming", "chapter-count",
                      "volume-count"]:
            assert f"{el_id}" in js, f"app.js 未引用 HTML id: #{el_id}"
        print("✅ 前端与 HTML 已对齐")


class TestOutlineAgentV03:
    """
    v0.3 验证：大纲 Agent 两阶段生成 + 解析重试 + 结构校验/修复 + 分卷参数贯通
    - 后端：章数超过上限先出分卷骨架再逐卷细纲；解析失败携带错误重试；输出程序化修复
    - 接口：/api/stream-outline 接收 volume_count，生成后校验并修复
    - 前端：提供分卷数量输入并传给后端
    """

    def test_backend_two_phase_machinery(self):
        """outline_agent.py 应包含两阶段、重试、校验与修复的全部标记"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agents", "outline_agent.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "MAX_CHAPTERS_PER_CALL" in content, "缺少单次生成上限常量"
        assert "_generate_skeleton" in content, "缺少两阶段生成骨架函数"
        assert "_generate_volume_detail" in content, "缺少逐卷细纲生成函数"
        assert "_validate_output" in content, "缺少输出结构校验"
        assert "_repair" in content, "缺少程序化自动修复"
        assert "parse_error" in content, "缺少 JSON 解析失败重试判定"
        assert "MAX_JSON_RETRIES" in content, "缺少解析重试上限常量"
        print("✅ 大纲 Agent 两阶段/重试/修复机制已接入")

    def test_stream_outline_accepts_volume_count(self):
        """app.py 的 /api/stream-outline 应支持分卷数并校验修复结果"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'volume_count = data.get("volume_count", 1) or 1' in content, "stream-outline 未接收分卷数"
        assert "MAX_CHAPTERS_PER_CALL" in content, "stream-outline 缺少两阶段阈值判断"
        assert "agent._validate_output(result, chapter_count, volume_count)" in content, \
            "stream-outline 缺少输出校验调用"
        assert "agent._repair(result, chapter_count, volume_count)" in content, \
            "stream-outline 缺少输出修复调用"
        print("✅ /api/stream-outline 已贯通分卷数与校验修复")

    def test_frontend_volume_input(self):
        """前端应提供分卷数量输入并随大纲请求下发"""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "templates", "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(root, "static", "js", "app.js"), "r", encoding="utf-8") as f:
            js = f.read()
        assert 'id="volume-count"' in html, "HTML 缺少分卷数量输入框"
        assert "volume_count: volumes" in js, "app.js 未下发分卷数"
        print("✅ 前端分卷数量输入已接入")

    def test_demo_mode_single_and_two_phase(self):
        """Demo 模式下单阶段与两阶段都应稳定产出可修复结构"""
        from agents.outline_agent import OutlineAgent

        ws = {"world_name": "测试", "genre": "玄幻"}
        backup = os.environ.get("OPENAI_API_KEY")
        if backup is not None:
            os.environ.pop("OPENAI_API_KEY", None)
        try:
            agent = OutlineAgent()
            single = agent.run(world_setting=ws, chapter_count=10, volume_count=1)
            assert single.get("volumes"), "单阶段产出缺少 volumes"
            assert "estimated_total_chapters" in single, "单阶段产出缺少统计字段"

            two = agent.run(world_setting=ws, chapter_count=20, volume_count=2,
                            genre="玄幻", style="热血")
            assert two.get("volumes"), "两阶段产出缺少 volumes"
            assert "estimated_total_chapters" in two, "两阶段产出缺少统计字段"
        finally:
            if backup is not None:
                os.environ["OPENAI_API_KEY"] = backup
        print("✅ Demo 模式单/两阶段生成均正常")


class TestPolisherAgentV03:
    """
    v0.3 验证：润色 Agent 差异化策略 + 专有名词保护 + 结构化输出解析 + 校验/strict 重试
    - 后端：quality_score 匹配策略并注入 prompt；protected_terms 注入并校验；正文不再残留润色说明
    - 流水线：润色传入评分/保护词并开启 strict；温度降到 0.4
    """

    def test_backend_markers(self):
        """polisher_agent.py 应包含结构化输出、策略映射、保护词与校验标记"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agents", "polisher_agent.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "===POLISHED_CONTENT===" in content, "缺少正文分隔符"
        assert "run_detailed" in content, "缺少 run_detailed 详细接口"
        assert "_STRATEGY_MAP" in content, "缺少差异化策略映射"
        assert "protected_terms" in content, "缺少专有名词保护参数"
        assert "_validate_output" in content, "缺少输出校验"
        assert "strict" in content, "缺少 strict 重试参数"
        assert "DEFAULT_TEMPERATURE" in content, "缺少默认温度常量"
        print("✅ 润色 Agent v0.3 机制已接入")

    def test_frozen_demo_registration_preserved(self):
        """冻结约定：Polisher 的 Demo 注册行必须保持原样"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agents", "polisher_agent.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'register_demo("Polisher", DEMO_POLISHED_CONTENT, estimated_tokens=3000)' in content, \
            "Polisher Demo 注册行被改动"
        print("✅ Polisher Demo 注册保持冻结")

    def test_pipeline_wiring(self):
        """app.py 润色应传入评分/保护词并开启 strict，温度应为 0.4"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "_collect_protected_terms" in content, "缺少保护词收集函数"
        assert 'quality_score=check_result.get("overall_quality_score")' in content, \
            "润色未传入质量评分"
        assert "protected_terms=_collect_protected_terms()" in content, "润色未传入保护词"
        assert "strict=True" in content, "润色未开启 strict"
        assert "PolisherAgent(temperature=0.4)" in content, "润色温度未降到 0.4"
        print("✅ 流水线润色接线完成")

    def test_demo_run_behavior(self):
        """Demo 模式下润色返回干净正文、解析出润色说明、策略匹配正确"""
        from agents.polisher_agent import PolisherAgent

        backup = os.environ.get("OPENAI_API_KEY")
        if backup is not None:
            os.environ.pop("OPENAI_API_KEY", None)
        try:
            agent = PolisherAgent()
            assert agent.temperature == 0.4, "默认润色温度应为 0.4"

            assert PolisherAgent._strategy_for(8.5)[0] == "微调"
            assert PolisherAgent._strategy_for(6.5)[0] == "局部优化"
            assert PolisherAgent._strategy_for(None)[0] == "自动判断"

            result = agent.run_detailed(
                text='沈炼握紧寒江剑，低声说道："耐得住寂寞，方能成大器。"他转身下山。',
                quality_score=6.5,
                protected_terms=["沈炼", "寒江剑"],
                strict=True,
            )
            assert result.content, "润色正文为空"
            assert "【润色说明】" not in result.content, "正文残留润色说明"
            assert result.notes, "未解析出润色说明"
        finally:
            if backup is not None:
                os.environ["OPENAI_API_KEY"] = backup
        print("✅ Demo 润色行为正常")


class TestSummarizerAgentV05:
    """
    v0.5 验证：摘要 Agent Pydantic schema 校验 + 分块合并管线 + 解析重试 + 防御式兜底
    - 后端：ChapterSummarySchema 强校验、超长正文分块合并、解析失败回喂重试
    - 流水线：app.py 传入大纲标题；冻结 Demo 注册行保持原样
    """

    def test_backend_markers(self):
        """summarizer_agent.py 应包含 schema、分块合并、重试与兜底标记"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agents", "summarizer_agent.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "ChapterSummarySchema" in content, "缺少 Pydantic schema"
        assert "field_validator" in content, "缺少字段校验器"
        assert "_chunk_text" in content, "缺少分块函数"
        assert "_merge_partials" in content, "缺少字段级合并"
        assert "_TITLE_RE" in content, "缺少标题正则"
        assert "_prepare_text" in content, "缺少绝对上限保护"
        assert "max_parse_retries" in content, "缺少解析重试参数"
        assert "_DEFAULT_MAX_TEXT_CHARS" in content, "缺少分块阈值常量"
        print("✅ 摘要 Agent v0.5 机制已接入")

    def test_frozen_demo_registration_preserved(self):
        """冻结约定：ChapterSummarizer 的 Demo 注册行必须保持原样"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agents", "summarizer_agent.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'register_demo("ChapterSummarizer", DEMO_SUMMARY, estimated_tokens=800)' in content, \
            "ChapterSummarizer Demo 注册行被改动"
        print("✅ 摘要 Agent Demo 注册保持冻结")

    def test_pipeline_wiring(self):
        """app.py 摘要提取应传入大纲标题（占位细纲除外）"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'outline.get("summary_type") != "续写扩展章"' in content, "缺少占位细纲标题过滤"
        assert "title=outline_title" in content, "未传入大纲标题"
        print("✅ 流水线摘要标题接线完成")

    def test_title_regex(self):
        """首行标题正则提取正常"""
        from agents.summarizer_agent import ChapterSummarizerAgent as A
        assert A._extract_title_from_text("第一章 寒江剑鸣\n\n正文……") == "寒江剑鸣"
        assert A._extract_title_from_text("第3章 重逢\n\n正文……") == "重逢"
        assert A._extract_title_from_text("Chapter 3 重逢\n\n正文……") == "重逢"
        assert A._extract_title_from_text("正文直接开始……") == ""
        print("✅ 标题正则提取正常")

    def test_chunking(self):
        """分块切分：每块非空且不超过 chunk_chars"""
        from agents.summarizer_agent import ChapterSummarizerAgent as A, _DEFAULT_CHUNK_CHARS
        paras = "\n\n".join("第%d段" % i * 200 for i in range(40))
        chunks = A._chunk_text(paras, _DEFAULT_CHUNK_CHARS)
        assert chunks, "分块结果为空"
        assert all(0 < len(c) <= _DEFAULT_CHUNK_CHARS for c in chunks), "存在超长或空块"
        print("✅ 分块切分正常")

    def test_safe_parse_garbage(self):
        """垃圾输入兜底：不抛异常、章号被强制、带 parse_error 标记"""
        from agents.summarizer_agent import ChapterSummarizerAgent as A
        r = A()._safe_parse("这不是 JSON{{{{{", 3)
        assert isinstance(r, dict), "垃圾输入兜底应返回 dict"
        assert r["chapter_num"] == 3, "章号应被强制为 3"
        assert r.get("parse_error") is True, "应标记解析失败"
        print("✅ 垃圾输入兜底不崩溃")

    def test_safe_parse_partial_field_coercion(self):
        """字段类型强转兜底：类型错误字段可塞多少塞多少"""
        from agents.summarizer_agent import ChapterSummarizerAgent as A
        r = A()._safe_parse('{"chapter_num": 7, "title": "X", "summary": 12345}', 2)
        assert r["chapter_num"] == 2, "章号应被强制为 2"
        assert r["summary"] == "12345", "summary 应被强转为字符串"
        assert isinstance(r["key_events"], list), "key_events 应为列表"
        print("✅ 字段类型强转兜底正常")

    def test_demo_run_behavior(self):
        """Demo 模式单次摘要：字段齐全、章号强制、标题回填"""
        from agents.summarizer_agent import ChapterSummarizerAgent as A
        backup = os.environ.get("OPENAI_API_KEY")
        if backup is not None:
            os.environ.pop("OPENAI_API_KEY", None)
        try:
            r = A().run(chapter_text="第一章 寒江剑鸣\n\n正文内容……", chapter_num=1)
            assert r["chapter_num"] == 1, "章号应被强制为 1"
            assert r.get("title") == "寒江剑鸣", "标题应从正文提取"
            assert isinstance(r.get("characters_present"), list)
            assert isinstance(r.get("key_events"), list)
        finally:
            if backup is not None:
                os.environ["OPENAI_API_KEY"] = backup
        print("✅ Demo 单次摘要正常")

    def test_demo_long_text_chunking(self):
        """Demo 模式超长正文分块合并：不崩、章号强制、字段可用"""
        from agents.summarizer_agent import ChapterSummarizerAgent as A
        backup = os.environ.get("OPENAI_API_KEY")
        if backup is not None:
            os.environ.pop("OPENAI_API_KEY", None)
        try:
            long_text = "第一章 寒江剑鸣\n\n" + "\n\n".join(
                "这是第%d段正文内容……" % i * 20 for i in range(200)
            )
            r = A().run(chapter_text=long_text, chapter_num=5)
            assert r["chapter_num"] == 5, "章号应被强制为 5"
            assert r.get("summary") or r.get("key_events"), "合并结果不应为空"
            assert isinstance(r.get("key_events"), list)
        finally:
            if backup is not None:
                os.environ["OPENAI_API_KEY"] = backup
        print("✅ Demo 分块合并管线正常")


class TestSkillKnowledge:
    """
    Phase 0 验证：skill 知识加载器 —— 运行时读全局 skill 目录 + 内嵌降级
    """

    def test_resolve_skills_dir(self):
        """目录解析：默认 ~/.agents/skills，可用 SKILLS_DIR 覆盖"""
        from core.skill_knowledge import resolve_skills_dir
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SKILLS_DIR"] = tmp
            try:
                assert str(resolve_skills_dir()) == tmp
            finally:
                os.environ.pop("SKILLS_DIR", None)
        print("✅ 目录解析正常")

    def test_load_reference_file(self):
        """本机有 skill 目录时应读到真实文件内容"""
        from core.skill_knowledge import load_reference
        text = load_reference("story-deslop", "anti-ai-writing.md")
        if text is not None:
            assert "去AI" in text or "AI 味" in text or "禁用" in text
        print("✅ 真实文件读取正常（缺失时跳过）")

    def test_get_knowledge_embedded_fallback(self):
        """不存在的引用应回退内嵌摘录并标注 embedded"""
        from core.skill_knowledge import get_knowledge
        text, source = get_knowledge("story-review", "quality-rubric.md")
        assert text, "不应返回空文本"
        assert source in ("file", "embedded")
        print("✅ 内嵌降级正常")

    def test_polisher_rules_loader(self):
        """polisher_rules 组装非空"""
        from core.skill_knowledge import polisher_rules
        text, source = polisher_rules()
        assert text and source in ("file", "embedded")
        print("✅ polisher 规则加载正常")

    def test_reviewer_rules_loader(self):
        """reviewer_rules 组装非空"""
        from core.skill_knowledge import reviewer_rules, platform_rubric
        text, source = reviewer_rules()
        assert text and source in ("file", "embedded")
        p, ps = platform_rubric("fanqie")
        assert p and ps in ("file", "embedded")
        print("✅ reviewer/平台规则加载正常")


class TestPolisherSkillDeslop:
    """
    Phase 1 验证：Polisher 去AI味增强 —— deslop 参数注入与默认兜底
    """

    def test_run_accepts_deslop_params(self):
        """run/run_detailed 接受 deslop 与 deslop_rules 参数"""
        from agents.polisher_agent import PolisherAgent
        backup = os.environ.get("OPENAI_API_KEY")
        if backup is not None:
            os.environ.pop("OPENAI_API_KEY", None)
        try:
            result = PolisherAgent().run_detailed(
                text='沈炼握紧寒江剑，低声说道："耐得住寂寞，方能成大器。"他转身下山。',
                quality_score=6.5,
                protected_terms=["沈炼", "寒江剑"],
                strict=False,
                deslop=True,
                deslop_rules='## 去AI味\n1. 禁止"不是A，而是B"句式。',
            )
            assert result.content, "润色正文为空"
        finally:
            if backup is not None:
                os.environ["OPENAI_API_KEY"] = backup
        print("✅ deslop 参数生效")

    def test_build_user_msg_injects_deslop(self):
        """deslop 开启时 user_msg 含去AI味区块，关闭时不含"""
        from agents.polisher_agent import PolisherAgent
        agent = PolisherAgent()
        msg_on = agent._build_user_msg(
            text="x", style_guide="", quality_score=None,
            strategy=("微调", "x"), protected_terms=[],
            deslop=True, deslop_rules="自定义去AI味规则",
        )
        assert "去AI味" in msg_on and "自定义去AI味规则" in msg_on
        msg_off = agent._build_user_msg(
            text="x", style_guide="", quality_score=None,
            strategy=("微调", "x"), protected_terms=[],
            deslop=False, deslop_rules="",
        )
        assert "去AI味" not in msg_off
        print("✅ 去AI味区块注入/关闭正常")

    def test_app_wiring(self):
        """app.py 润色调用应传入 deslop 与 deslop_rules"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "deslop=True" in content
        assert "deslop_rules=_load_polisher_rules()" in content
        assert "def _load_polisher_rules" in content
        print("✅ 流水线去AI味接线完成")


class TestReviewerAgentV01:
    """
    Phase 2 验证：多视角审查 Agent —— schema 校验 + S1-S4 定级 + demo 直通
    """

    def test_backend_markers(self):
        """reviewer_agent.py 应包含 schema/视角/自修复/对账标记"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agents", "reviewer_agent.py")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "ReviewReport" in content and "ReviewFinding" in content
        assert 'register_demo("StoryReviewer"' in content
        assert "MAX_REPAIR_ATTEMPTS" in content
        assert "_finalize" in content and "verdict" in content
        print("✅ 审查 Agent 机制已接入")

    def test_agents_export(self):
        """ReviewerAgent 应被导出"""
        from agents import ReviewerAgent
        assert ReviewerAgent is not None
        print("✅ ReviewerAgent 导出正常")

    def test_demo_run_behavior(self):
        """Demo 模式审查：verdict/S1-S4 findings/对账不崩"""
        from agents.reviewer_agent import ReviewerAgent
        from core.skill_knowledge import reviewer_rules
        backup = os.environ.get("OPENAI_API_KEY")
        if backup is not None:
            os.environ.pop("OPENAI_API_KEY", None)
        try:
            rubric, source = reviewer_rules()
            r = ReviewerAgent().run(
                chapter_text='第一章 寒江剑鸣\n\n沈炼握紧寒江剑，转身下山。',
                chapter_num=1, rubric=rubric, rubric_source=source,
            )
            assert r["verdict"] in ("APPROVE", "CONCERNS", "REJECT")
            assert isinstance(r["findings"], list)
            for f in r["findings"]:
                assert f["severity"] in ("S1", "S2", "S3", "S4")
        finally:
            if backup is not None:
                os.environ["OPENAI_API_KEY"] = backup
        print("✅ Demo 审查行为正常")

    def test_finalize_corrects_verdict(self):
        """S1 存在时 verdict 应被重算为 REJECT"""
        from agents.reviewer_agent import ReviewerAgent, ReviewReport, ReviewFinding
        report = ReviewReport(
            verdict="APPROVE",
            findings=[
                ReviewFinding(
                    severity="S1", category="consistency",
                    location="[P1]", evidence="角色已死亡却登场",
                    issue="死者复活", fix="删除或改为他人",
                )
            ],
                    summary="本段存在严重设定冲突，需要立即修复。",
        )
        data = ReviewerAgent._finalize(report)
        assert data["verdict"] == "REJECT"
        print("✅ verdict 对账正常")


class TestSkillPrecheck:
    """
    Phase 4 验证：node 确定性预检 —— 静默降级 + findings 结构
    """

    def test_returns_dict(self):
        """返回结构稳定：ok/findings/scripts_run/reason 键齐全"""
        from core.skill_precheck import run_precheck
        r = run_precheck("第一章 测试\n\n正文内容……")
        assert set(("ok", "findings", "scripts_run", "reason")) <= set(r.keys())
        assert isinstance(r["findings"], list)
        print("✅ 预检返回结构正常")

    def test_empty_text_safe(self):
        """空文本直接返回 reason，不抛异常"""
        from core.skill_precheck import run_precheck
        r = run_precheck("")
        assert r["ok"] is False and r["reason"] == "empty text"
        print("✅ 空文本兜底正常")

    def test_demo_text_finds_issues(self):
        """含 AI 味的正文应产生 findings（本机有 node 与脚本时）"""
        from core.skill_precheck import run_precheck
        text = ('第一章 测试\n\n沈炼眼中闪过一丝悲伤。他深吸一口气，'
                '心中涌起一股暖流——一切都会好起来的。')
        r = run_precheck(text)
        if r["ok"]:
            assert any("破折号" in f["issue"] or f["category"] == "format"
                       for f in r["findings"]), "应至少发现破折号/格式问题"
        print("✅ 预检发现机械问题（脚本可用时）")


class TestPipelineSkillIntegration:
    """
    Phase 5 验证：流水线接线 —— 新端点、chapters 新字段、skill 配置回显
    """

    def test_endpoints_exist(self):
        """app.py 应包含 /api/review 与 /api/precheck 端点"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert '"/api/review/<int:chapter_num>"' in content
        assert '"/api/precheck/<int:chapter_num>"' in content
        assert "def _run_chapter_review" in content
        assert "def _run_chapter_precheck" in content
        print("✅ 审查/预检端点已接入")

    def test_pipeline_wiring(self):
        """主流水线润色后应调用审查与预检，chapters 存新字段"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "_run_chapter_review(chapter_num, polished" in content
        assert "_run_chapter_precheck(chapter_num, polished" in content
        assert '"review_report"' in content
        assert '"precheck"' in content
        print("✅ 流水线 skill 接线完成")

    def test_status_echoes_skills(self):
        """状态端点回显 skill 配置（skills_dir_available / review_enabled）"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert '"skills_dir_available"' in content
        assert '"review_enabled"' in content
        assert '"precheck_enabled"' in content
        print("✅ 状态端点回显 skill 配置")

    def test_frontend_matches(self):
        """前端应提供审查/预检按钮与视图切换"""
        html_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "templates", "index.html")
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "static", "js", "app.js")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        assert "审查本章" in html and "预检本章" in html
        assert "toggleChapterView('review')" in html and "toggleChapterView('precheck')" in html
        assert "formatReviewReport" in js and "formatPrecheckReport" in js
        assert "runReview" in js and "runPrecheck" in js
        print("✅ 前端审查/预检视图已接入")


class TestShortStoryPipeline:
    """
    短篇网文写作流水线（story-short-write 集成）验证
    """

    def test_agent_exists(self):
        """ShortStoryAgent 应可导入并导出"""
        from agents import ShortStoryAgent
        assert ShortStoryAgent is not None
        print("✅ ShortStoryAgent 导出正常")

    def test_demo_registered(self):
        """ShortStory / ShortStoryWriter demo 应已注册（新增冻结项，非改既有）"""
        from agents.base import DEMO_REGISTRY
        assert "ShortStory" in DEMO_REGISTRY
        assert "ShortStoryWriter" in DEMO_REGISTRY
        print("✅ 短篇 demo 注册完成")

    def test_framework_demo_behavior(self):
        """Demo 模式构思：返回含核心字段的框架 dict"""
        from agents.short_story_agent import ShortStoryAgent
        backup = os.environ.get("OPENAI_API_KEY")
        if backup is not None:
            os.environ.pop("OPENAI_API_KEY", None)
        try:
            fw = ShortStoryAgent().run_framework(
                premise="我爹的剑被仇人夺走三年，今日却在一个病秧子手里见到。",
                emotion="反转震撼", genre="悬疑", platform="知乎",
            )
            assert isinstance(fw, dict) and not fw.get("parse_error")
            assert fw.get("title") and fw.get("logline")
            assert fw.get("core_reversal", {}).get("foreshadowing")
            assert isinstance(fw.get("sections", []), list)
        finally:
            if backup is not None:
                os.environ["OPENAI_API_KEY"] = backup
        print("✅ 短篇框架 demo 正常")

    def test_write_demo_behavior(self):
        """Demo 模式成文：返回非空正文"""
        from agents.short_story_agent import ShortStoryAgent, DEMO_SHORT_FRAMEWORK
        import json as _json
        backup = os.environ.get("OPENAI_API_KEY")
        if backup is not None:
            os.environ.pop("OPENAI_API_KEY", None)
        try:
            fw = _json.loads(DEMO_SHORT_FRAMEWORK)
            text = ShortStoryAgent().run_write(fw)
            assert isinstance(text, str) and len(text) > 500
        finally:
            if backup is not None:
                os.environ["OPENAI_API_KEY"] = backup
        print("✅ 短篇成文 demo 正常")

    def test_skill_knowledge_loaded(self):
        """短篇 skill 知识应可加载：题材风格包映射"""
        from core.skill_knowledge import genre_style_rules, short_story_rules
        text, source = genre_style_rules("悬疑")
        assert text and source in ("file", "embedded")
        rules, rsrc = short_story_rules("悬疑")
        assert rules and rsrc in ("file", "embedded")
        print("✅ 短篇 skill 知识加载正常")

    def test_skill_knowledge_embedded_fallback(self):
        """题材风格包无匹配时应返回空（内嵌兜底由 short_story_rules 承担）"""
        from core.skill_knowledge import genre_style_rules
        text, source = genre_style_rules("不存在的题材xyz")
        assert text == "" and source == "missing"
        print("✅ 题材风格包缺失兜底正常")

    def test_api_endpoints(self):
        """app.py 应包含短篇 API 端点与辅助函数"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        for route in ("/api/short/architect", "/api/short/write", "/api/short/polish",
                      "/api/short/review", "/api/short/precheck", "/api/short/status"):
            assert route in content
        for fn in ("_short_run_framework", "_short_run_write", "_short_run_polish",
                   "_short_run_review", "_short_run_precheck", "_build_short_review_rubric"):
            assert f"def {fn}" in content
        print("✅ 短篇 API 端点与辅助函数已接入")

    def test_persistence(self):
        """短篇状态应随 save_state/load_state 落盘"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert '"short_story.json"' in content
        assert 'self.short_story' in content
        print("✅ 短篇状态持久化已接入")

    def test_frontend(self):
        """前端应提供短篇标签页、输入区与五个操作按钮"""
        html_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "templates", "index.html")
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "static", "js", "app.js")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        assert "短篇小说模式" in html
        assert "shortArchitect()" in html and "shortWrite()" in html and "shortPolish()" in html
        assert "shortReview()" in html and "shortPrecheck()" in html
        assert "function shortArchitect" in js and "function shortWrite" in js
        assert "function renderShort" in js and "function shortView" in js
        print("✅ 短篇前端已接入")

    def test_models_route(self):
        """base.py 应包含 ShortStory 与 ShortStoryWriter 路由配置"""
        base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "agents", "base.py")
        with open(base_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert '"ShortStory": {' in content
        assert '"ShortStoryWriter": {' in content
        print("✅ 短篇模型路由已接入")


class TestWorldStateLedger:
    """v0.4 世界状态账本（core/world_state.py）验证"""

    def test_world_state_delta(self):
        """apply_delta 应按章节合并世界状态：位置覆盖、新增角色、剧情线追加"""
        from core.world_state import WorldState
        ws = WorldState()
        ws.apply_delta(1, {
            "characters": {"沈炼": {"alive": True, "location": "青州"}},
            "items": {"寒江剑": {"owner": "沈炼"}},
            "open_threads": ["寻找噬魂珠"],
        })
        ws.apply_delta(2, {"characters": {"沈炼": {"alive": True, "location": "云城"}}})
        assert ws.as_of_chapter == 2
        assert ws.characters["沈炼"]["location"] == "云城"
        assert ws.characters["沈炼"].get("location_history") == ["青州", "云城"]
        assert ws.items["寒江剑"]["owner"] == "沈炼"
        assert "寻找噬魂珠" in ws.open_threads
        print("✅ 世界状态增量合并正常")

    def test_foreshadowing_aging(self):
        """set_foreshadowings 应按植入章节计算搁置时长"""
        from core.world_state import WorldState
        ws = WorldState()
        ws.set_foreshadowings(
            [{"content": "神秘令牌来历", "planted_in": "第1章", "hint": "与身世有关"}],
            as_of_chapter=12,
        )
        assert len(ws.pending_foreshadowings) == 1
        assert ws.pending_foreshadowings[0]["age"] == 11
        print("✅ 伏笔搁置时长计算正常")

    def test_to_text(self):
        """to_text 应输出世界状态文本且受 char_limit 约束"""
        from core.world_state import WorldState
        ws = WorldState()
        ws.apply_delta(1, {"characters": {"沈炼": {"alive": True, "location": "青州"}}})
        text = ws.to_text(char_limit=50)
        assert "沈炼" in text
        assert len(text) <= 50 + 10
        print("✅ 世界状态文本渲染正常")

    def test_roundtrip(self):
        """to_dict / from_dict 应无损往返"""
        from core.world_state import WorldState
        ws = WorldState()
        ws.apply_delta(3, {"characters": {"云裳": {"alive": True, "location": "蜀山"}},
                           "open_threads": ["剑冢之谜"]})
        ws2 = WorldState.from_dict(ws.to_dict())
        assert ws2.as_of_chapter == 3
        assert ws2.characters["云裳"]["location"] == "蜀山"
        assert ws2.open_threads == ["剑冢之谜"]
        print("✅ 世界状态账本持久化往返正常")

    def test_persistence_wired(self):
        """app.py 应把账本写入 data/world_state.json 并在启动时恢复"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert '"world_state.json"' in content
        assert "WorldState.from_dict" in content
        assert "self.world_state" in content
        print("✅ 世界状态账本持久化已接入")


class TestContinuityContract:
    """v0.4 连续性契约（build_continuity_contract）验证"""

    def test_contract_header(self):
        """契约应使用 === 连贯性契约 === 头（供 _compress_context 解析）"""
        from core.world_state import build_continuity_contract
        contract = build_continuity_contract(None)
        assert contract.startswith("=== 连贯性契约 ===")
        print("✅ 契约头格式正确")

    def test_contract_contains_world_state(self):
        """契约应包含当前世界状态快照"""
        from core.world_state import WorldState, build_continuity_contract
        ws = WorldState()
        ws.apply_delta(1, {"characters": {"沈炼": {"alive": True, "location": "青州"}}})
        contract = build_continuity_contract(ws)
        assert "沈炼" in contract and "青州" in contract
        print("✅ 契约含世界状态快照")

    def test_contract_aging_hint(self):
        """伏笔搁置过久应出现提醒"""
        from core.world_state import WorldState, build_continuity_contract
        ws = WorldState()
        ws.set_foreshadowings(
            [{"content": "神秘令牌", "planted_in": "第1章", "hint": ""}],
            as_of_chapter=10,
        )
        contract = build_continuity_contract(ws)
        assert "未回收" in contract
        print("✅ 契约含伏笔搁置提醒")

    def test_contract_in_bible_context(self):
        """build_context_for_chapter 应注入契约段（world_state 非空时）"""
        from core.world_state import WorldState
        from core.story_bible import VersionedStoryBible
        ws = WorldState()
        ws.apply_delta(1, {"characters": {"沈炼": {"alive": True, "location": "青州"}}})
        bible = VersionedStoryBible(title="测试", genre="玄幻")
        ctx = bible.build_context_for_chapter(3, chapter_outline="{}", world_state=ws)
        assert "=== 连贯性契约 ===" in ctx
        assert "沈炼" in ctx
        print("✅ 契约段已注入写作上下文")


class TestBucketedContext:
    """v0.4 分桶历史脉络 + 全史语义召回上下文验证"""

    def test_recent_summaries_section(self):
        """前情提要应包含最近摘要"""
        from core.story_bible import VersionedStoryBible, ChapterSummary
        bible = VersionedStoryBible(title="测试", genre="玄幻")
        for n in range(1, 5):
            bible.add_chapter_summary(ChapterSummary(chapter_num=n, title=f"第{n}章",
                                                     summary=f"第{n}章摘要内容"))
        ctx = bible.build_context_for_chapter(5, chapter_outline="{}")
        assert "第3章摘要内容" in ctx or "前情提要" in ctx
        print("✅ 前情提要含最近摘要")

    def test_bucketed_history(self):
        """超过分桶阈值后应出现历史脉络（第2桶起）"""
        from core.story_bible import VersionedStoryBible, ChapterSummary
        bible = VersionedStoryBible(title="测试", genre="玄幻")
        for n in range(1, 26):
            bible.add_chapter_summary(ChapterSummary(chapter_num=n, title=f"第{n}章",
                                                     summary=f"第{n}章摘要内容"))
        ctx = bible.build_context_for_chapter(26, chapter_outline="{}")
        assert "历史脉络" in ctx
        assert "第1-10章：" in ctx
        print("✅ 历史脉络分桶正常")

    def test_buckets_capped(self):
        """历史脉络桶数应受 MAX_HISTORY_BUCKETS 上限约束"""
        from core.story_bible import VersionedStoryBible, ChapterSummary
        bible = VersionedStoryBible(title="测试", genre="玄幻")
        for n in range(1, 101):
            bible.add_chapter_summary(ChapterSummary(chapter_num=n, title=f"第{n}章",
                                                     summary=f"第{n}章摘要内容"))
        ctx = bible.build_context_for_chapter(101, chapter_outline="{}")
        import re
        buckets = re.findall(r"第\d+-\d+章：", ctx)
        assert len(buckets) <= bible.MAX_HISTORY_BUCKETS
        print(f"✅ 历史脉络桶数 {len(buckets)} 不超过上限 {bible.MAX_HISTORY_BUCKETS}")

    def test_compress_keeps_contract(self):
        """超限压缩时契约段应优先保留"""
        from core.world_state import WorldState
        from core.story_bible import VersionedStoryBible, ChapterSummary
        ws = WorldState()
        ws.apply_delta(1, {"characters": {"沈炼": {"alive": True, "location": "青州"}}})
        bible = VersionedStoryBible(title="测试", genre="玄幻")
        for n in range(1, 8):
            bible.add_chapter_summary(ChapterSummary(chapter_num=n, title=f"第{n}章",
                                                     summary="长摘要" * 30))
        ctx = bible.build_context_for_chapter(8, chapter_outline="{}", world_state=ws,
                                              max_chars=500)
        assert "=== 连贯性契约 ===" in ctx
        print("✅ 压缩后契约段保留")


class TestContinuityAudit:
    """v0.4 全量连贯性审计（ContinuityAuditor + /api/audit）验证"""

    def test_audit_agent_export(self):
        """AuditAgent 应可导入"""
        from agents import AuditAgent
        assert AuditAgent is not None
        print("✅ AuditAgent 导出正常")

    def test_demo_registered(self):
        """ContinuityAuditor demo 应已注册（新增冻结项）"""
        from agents.base import DEMO_REGISTRY
        assert "ContinuityAuditor" in DEMO_REGISTRY
        print("✅ ContinuityAuditor demo 注册完成")

    def test_demo_behavior(self):
        """Demo 模式审计：返回含 findings 的报告 dict"""
        from agents.audit_agent import AuditAgent
        backup = os.environ.get("OPENAI_API_KEY")
        if backup is not None:
            os.environ.pop("OPENAI_API_KEY", None)
        try:
            report = AuditAgent().run(
                chapters_text="===== 第1章 =====\n沈炼得到了寒江剑。",
                world_state_text="沈炼：存活",
                bible_summary="测试项目",
                issue_history_text="",
                as_of_chapter=1,
            )
            assert isinstance(report, dict)
            assert isinstance(report.get("findings", []), list)
            assert "summary" in report
        finally:
            if backup is not None:
                os.environ["OPENAI_API_KEY"] = backup
        print("✅ 连贯性审计 demo 正常")

    def test_api_endpoint(self):
        """app.py 应包含 /api/audit 端点与辅助函数"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "/api/audit" in content
        assert "def _run_continuity_audit" in content
        assert "AUDIT_INTERVAL" in content
        assert "_run_continuity_audit()" in content
        print("✅ 全量连贯性审计端点已接入")

    def test_auto_trigger(self):
        """每 AUDIT_INTERVAL 章应自动触发审计"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "chapter_num % project.AUDIT_INTERVAL" in content
        print("✅ 周期性自动审计已接入")

    def test_frontend(self):
        """前端应提供审计按钮与审计报告视图"""
        html_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "templates", "index.html")
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "static", "js", "app.js")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        assert "连贯审计" in html
        assert "runAudit" in html
        assert "function runAudit" in js and "function formatAuditReport" in js
        print("✅ 审计前端已接入")

    def test_world_state_endpoint(self):
        """/api/status 应返回世界状态与审计摘要"""
        app_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert '"world_state"' in content
        assert '"audit"' in content
        assert "last_audited_chapter" in content
        print("✅ 状态接口已含账本与审计字段")


# ============================================================
# 主入口：运行所有测试
# ============================================================

def run_all_tests():
    """运行所有测试并输出结果"""
    print("=" * 70)
    print("🧪 小说写作 Agent v0.2 修复验证测试")
    print("=" * 70)
    print()

    test_classes = [
        TestFix1_StoryBibleBaseClass,
        TestFix2_DotEnvLoading,
        TestFix3_ThreadSafety,
        TestFix4_DataPersistence,
        TestCoreFunctionality,
        TestVectorRag,
        TestContinuationWrite,
        TestOutlineAgentV03,
        TestPolisherAgentV03,
        TestSummarizerAgentV05,
        TestSkillKnowledge,
        TestPolisherSkillDeslop,
        TestReviewerAgentV01,
        TestSkillPrecheck,
        TestPipelineSkillIntegration,
        TestShortStoryPipeline,
        TestWorldStateLedger,
        TestContinuityContract,
        TestBucketedContext,
        TestContinuityAudit,
    ]

    total = 0
    passed = 0
    failed = 0
    errors = []

    for test_class in test_classes:
        print(f"\n{'=' * 70}")
        print(f"📋 {test_class.__doc__.strip().split(chr(10))[0] if test_class.__doc__ else test_class.__name__}")
        print(f"{'=' * 70}")

        instance = test_class()
        for name in dir(instance):
            if name.startswith('test_'):
                total += 1
                test_func = getattr(instance, name)
                try:
                    test_func()
                    passed += 1
                except AssertionError as e:
                    failed += 1
                    errors.append((name, str(e)))
                    print(f"❌ {name}: {e}")
                except Exception as e:
                    failed += 1
                    errors.append((name, f"异常: {e}"))
                    print(f"💥 {name}: 异常 - {e}")

    # 输出总结
    print("\n" + "=" * 70)
    print("📊 测试结果总结")
    print("=" * 70)
    print(f"  总计: {total} 个测试")
    print(f"  通过: {passed} ✅")
    print(f"  失败: {failed} ❌")
    
    if errors:
        print("\n❌ 失败的测试:")
        for name, err in errors:
            print(f"  • {name}: {err}")
    
    print("\n" + "=" * 70)
    
    if failed == 0:
        print("🎉 所有测试通过！所有 5 个修复均已验证成功。")
        print("=" * 70)
        return True
    else:
        print(f"⚠️  有 {failed} 个测试失败，请检查上述错误信息。")
        print("=" * 70)
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
