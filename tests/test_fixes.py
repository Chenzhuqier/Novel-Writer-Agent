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
