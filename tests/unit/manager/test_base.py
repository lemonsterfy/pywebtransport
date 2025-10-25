"""Unit tests for the pywebtransport.manager._base module."""

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport.manager._base import _BaseResourceManager


class MockResource:
    def __init__(self, resource_id: str):
        self.resource_id = resource_id
        self._is_closed = False
        self.close_mock = AsyncMock()

    async def close(self) -> None:
        self._is_closed = True
        await self.close_mock()

    def is_closed(self) -> bool:
        return self._is_closed


class ConcreteResourceManager(_BaseResourceManager[str, MockResource]):
    async def _close_resource(self, resource: MockResource) -> None:
        await resource.close()

    def _get_resource_id(self, resource: MockResource) -> str:
        return resource.resource_id

    def _is_resource_closed(self, resource: MockResource) -> bool:
        return resource.is_closed()

    async def add_resource(self, resource: MockResource) -> None:
        if self._lock is None:
            self._resources[resource.resource_id] = resource
            return
        async with self._lock:
            self._resources[resource.resource_id] = resource
            self._stats["total_created"] += 1
            self._update_stats_unsafe()


@pytest.fixture
def manager() -> ConcreteResourceManager:
    return ConcreteResourceManager(resource_name="resource", max_resources=10, cleanup_interval=0.01)


@pytest_asyncio.fixture
async def running_manager(
    manager: ConcreteResourceManager,
) -> AsyncGenerator[ConcreteResourceManager, None]:
    async with manager as mgr:
        yield mgr


class TestBaseResourceManager:
    @pytest.mark.asyncio
    async def test_abstract_methods_raise(self, manager: ConcreteResourceManager) -> None:
        with pytest.raises(NotImplementedError):
            await _BaseResourceManager._close_resource(manager, MockResource("r1"))

        with pytest.raises(NotImplementedError):
            _BaseResourceManager._get_resource_id(manager, MockResource("r1"))

        with pytest.raises(NotImplementedError):
            _BaseResourceManager._is_resource_closed(manager, MockResource("r1"))

    @pytest.mark.asyncio
    async def test_async_context_manager(self, manager: ConcreteResourceManager, mocker: MockerFixture) -> None:
        start_spy = mocker.spy(manager, "_start_background_tasks")
        shutdown_spy = mocker.spy(manager, "shutdown")

        async with manager as mgr:
            assert mgr is manager
            assert manager._lock is not None
            start_spy.assert_called_once()

        shutdown_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_background_task_done_callback(
        self, running_manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        shutdown_spy = mocker.spy(running_manager, "shutdown")
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = ValueError("test")

        running_manager._on_background_task_done(mock_task)
        await asyncio.sleep(0)

        shutdown_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_background_task_done_cancelled(
        self, running_manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        shutdown_spy = mocker.spy(running_manager, "shutdown")
        mock_task.cancelled.return_value = True
        mock_task.exception.return_value = None

        running_manager._on_background_task_done(mock_task)

        shutdown_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_background_task_done_no_exception(
        self, running_manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        shutdown_spy = mocker.spy(running_manager, "shutdown")
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = None

        running_manager._on_background_task_done(mock_task)

        shutdown_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_background_task_done_when_shutting_down(
        self, running_manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        mock_task.exception.return_value = ValueError("test")
        shutdown_spy = mocker.spy(running_manager, "shutdown")
        running_manager._is_shutting_down = True
        running_manager._on_background_task_done(mock_task)
        shutdown_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_background_tasks(self, manager: ConcreteResourceManager, mocker: MockerFixture) -> None:
        task1 = mocker.create_autospec(asyncio.Task, instance=True)
        task1.done.return_value = False
        task2 = mocker.create_autospec(asyncio.Task, instance=True)
        task2.done.return_value = True
        manager._cleanup_task = mocker.create_autospec(asyncio.Task, instance=True)
        setattr(manager, "_background_tasks_to_cancel", [task1, task2])

        mock_gather = mocker.patch("asyncio.gather", new_callable=AsyncMock)

        await manager._cancel_background_tasks()

        task1.cancel.assert_called_once()
        task2.cancel.assert_not_called()
        mock_gather.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_closed_resources(self, running_manager: ConcreteResourceManager) -> None:
        resource1 = MockResource("r1")
        resource2 = MockResource("r2")
        await resource2.close()
        await running_manager.add_resource(resource1)
        await running_manager.add_resource(resource2)

        assert len(running_manager) == 2
        cleaned_count = await running_manager.cleanup_closed_resources()

        assert cleaned_count == 1
        assert len(running_manager) == 1
        resources = await running_manager.get_all_resources()
        assert resources[0] is resource1

    @pytest.mark.asyncio
    async def test_cleanup_closed_resources_none_closed(self, running_manager: ConcreteResourceManager) -> None:
        await running_manager.add_resource(MockResource("r1"))
        cleaned_count = await running_manager.cleanup_closed_resources()
        assert cleaned_count == 0

    @pytest.mark.asyncio
    async def test_close_all_resources(self, running_manager: ConcreteResourceManager) -> None:
        resource1 = MockResource("r1")
        resource2 = MockResource("r2")
        await running_manager.add_resource(resource1)
        await running_manager.add_resource(resource2)

        await running_manager._close_all_resources()

        resource1.close_mock.assert_awaited_once()
        resource2.close_mock.assert_awaited_once()
        assert len(running_manager._resources) == 0
        stats = await running_manager.get_stats()
        assert stats["total_closed"] == 2

    @pytest.mark.asyncio
    async def test_close_all_resources_before_start(self, manager: ConcreteResourceManager) -> None:
        manager._resources["r1"] = MockResource("r1")
        await manager._close_all_resources()
        assert len(manager._resources) == 1

    @pytest.mark.asyncio
    async def test_close_all_resources_exception_group(
        self, running_manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        resource = MockResource("r1")
        await running_manager.add_resource(resource)
        resource.close_mock.side_effect = ValueError("test error")
        log_spy = mocker.spy(running_manager._log, "error")

        await running_manager._close_all_resources()
        log_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all_resources_no_resources(
        self, running_manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        log_spy = mocker.spy(running_manager._log, "info")
        await running_manager._close_all_resources()
        assert log_spy.call_count == 0

    @pytest.mark.asyncio
    async def test_get_resources(self, running_manager: ConcreteResourceManager) -> None:
        resource1 = MockResource("r1")
        await running_manager.add_resource(resource1)

        all_resources = await running_manager.get_all_resources()
        assert all_resources == [resource1]

        found_resource = await running_manager.get_resource(resource_id="r1")
        assert found_resource is resource1

        not_found_resource = await running_manager.get_resource(resource_id="r2")
        assert not_found_resource is None

    @pytest.mark.asyncio
    async def test_get_stats(self, running_manager: ConcreteResourceManager) -> None:
        await running_manager.add_resource(MockResource("r1"))
        stats = await running_manager.get_stats()

        assert stats["total_created"] == 1
        assert stats["current_count"] == 1
        assert stats["max_concurrent"] == 1
        assert stats["active"] == 1
        assert stats["max_resources"] == 10

    def test_initialization(self, manager: ConcreteResourceManager) -> None:
        assert manager._resource_name == "resource"
        assert manager._max_resources == 10
        assert manager._cleanup_interval == 0.01
        assert len(manager) == 0

    @pytest.mark.asyncio
    async def test_methods_before_start(self, manager: ConcreteResourceManager) -> None:
        assert await manager.get_all_resources() == []
        assert await manager.get_resource(resource_id="r1") is None
        assert await manager.get_stats() == {}
        assert await manager.cleanup_closed_resources() == 0

    @pytest.mark.asyncio
    async def test_periodic_cleanup_exception(
        self, running_manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        sleep_mock = mocker.patch("asyncio.sleep", new_callable=AsyncMock)
        sleep_mock.side_effect = [asyncio.CancelledError]
        cleanup_mock = mocker.patch.object(running_manager, "cleanup_closed_resources", side_effect=ValueError("test"))
        log_spy = mocker.spy(running_manager._log, "error")

        await running_manager._periodic_cleanup()

        cleanup_mock.assert_called_once()
        log_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_periodic_cleanup_loop(self, running_manager: ConcreteResourceManager, mocker: MockerFixture) -> None:
        sleep_mock = mocker.patch("asyncio.sleep", new_callable=AsyncMock)
        sleep_mock.side_effect = [None, asyncio.CancelledError]
        cleanup_spy = mocker.spy(running_manager, "cleanup_closed_resources")

        await running_manager._periodic_cleanup()

        assert cleanup_spy.call_count == 2
        assert sleep_mock.call_count == 2

    @pytest.mark.asyncio
    async def test_shutdown(self, running_manager: ConcreteResourceManager, mocker: MockerFixture) -> None:
        cancel_spy = mocker.spy(running_manager, "_cancel_background_tasks")
        close_all_spy = mocker.spy(running_manager, "_close_all_resources")

        await running_manager.shutdown()

        assert running_manager._is_shutting_down is True
        cancel_spy.assert_called_once()
        close_all_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_idempotency(self, running_manager: ConcreteResourceManager, mocker: MockerFixture) -> None:
        running_manager._is_shutting_down = True
        log_spy = mocker.spy(running_manager._log, "info")

        await running_manager.shutdown()

        log_spy.assert_not_called()
