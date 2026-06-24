"""
Demo 05: Teammate 生命周期 + cleanup_spawned_in_turn 焚毁。

跑法：
    python learn/05-memory-persistence/05-cleanup-and-lifecycle/demo_cleanup.py

观察点：
  1. spawn → asyncio.Task 启动
  2. cleanup → cancel + await → Task.done() = True
  3. 焚毁后再 spawn 同名 → 全新实例（独立记忆）

不依赖项目代码，用最小 asyncio 模型演示焚毁机制。
"""

import asyncio


class FakeRunner:
    """模拟 Runner：一个不退出的 asyncio.Task。"""

    def __init__(self, name: str):
        self.name = name
        self.task: asyncio.Task | None = None
        self.processed = 0

    async def _loop(self):
        try:
            while True:
                await asyncio.sleep(0.1)
                self.processed += 1
        except asyncio.CancelledError:
            # 模拟 shutdown 收尾
            raise

    def start(self):
        self.task = asyncio.create_task(self._loop(), name=f"fake-{self.name}")

    async def shutdown(self):
        if self.task is None:
            return
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass


class FakeTeamManager:
    """模拟 TeamManager：维护 _spawned_this_turn 集合 + cleanup。"""

    def __init__(self):
        self.members: dict[str, FakeRunner] = {}
        self._spawned_this_turn: set[str] = set()

    def spawn(self, name: str) -> FakeRunner:
        if name in self.members:
            raise ValueError(f"{name} 已存在")
        r = FakeRunner(name)
        r.start()
        self.members[name] = r
        self._spawned_this_turn.add(name)
        return r

    async def cleanup_spawned_in_turn(self) -> int:
        targets = list(self._spawned_this_turn)
        self._spawned_this_turn.clear()
        for name in targets:
            r = self.members.pop(name, None)
            if r is not None:
                await r.shutdown()
        return len(targets)

    def active(self) -> int:
        return sum(1 for r in self.members.values() if r.task and not r.task.done())


async def main():
    tm = FakeTeamManager()

    print("=== 起 3 个 Teammate ===")
    tm.spawn("alice")
    tm.spawn("bob")
    tm.spawn("carol")
    print(f"  活跃: {tm.active()}")

    print("\n=== 第一轮工作中... ===")
    await asyncio.sleep(0.5)
    snapshots = [(name, r.processed) for name, r in tm.members.items()]
    print(f"  活跃: {tm.active()}   (各自处理了 {dict(snapshots)} 轮 sleep)")

    print("\n=== cleanup_spawned_in_turn ===")
    n = await tm.cleanup_spawned_in_turn()
    print(f"  焚毁数: {n}")
    print(f"  活跃: {tm.active()}   ✓ 全焚干净")
    print(f"  _spawned_this_turn: {tm._spawned_this_turn}")

    print("\n=== 下一轮：起一个新的同名 Teammate ===")
    new_alice = tm.spawn("alice")
    await asyncio.sleep(0.2)
    print(f"  活跃: {tm.active()}   ← 全新实例（processed={new_alice.processed}，与上一轮无关）")

    print("\n=== 退出前清理 ===")
    await tm.cleanup_spawned_in_turn()
    print(f"  活跃: {tm.active()}")


if __name__ == "__main__":
    asyncio.run(main())
