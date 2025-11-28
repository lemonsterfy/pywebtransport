"""Unit tests for the pywebtransport.manager._base module."""

import asyncio

import pytest
from pytest_mock import MockerFixture

from pywebtransport.events import Event, EventEmitter
from pywebtransport.manager._base import _BaseResourceManager
from pywebtransport.types import EventType


class MockResource:
    def __init__(self, resource_id: str) -> None:
        self.resource_id = resource_id
        self.events = EventEmitter()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class ConcreteResourceManager(_BaseResourceManager[str, MockResource]):
    _resource_closed_event_type = EventType.CONNECTION_CLOSED

    async def _close_resource(self, resource: MockResource) -> None:
        await resource.close()

    def _get_resource_id(self, resource: MockResource) -> str:
        return resource.resource_id


@pytest.mark.asyncio
class TestBaseResourceManager:
    @pytest.fixture
    def manager(self) -> ConcreteResourceManager:
        return ConcreteResourceManager(resource_name="test_item", max_resources=5)

    async def test_add_resource(self, manager: ConcreteResourceManager) -> None:
        resource = MockResource("r1")

        async with manager:
            await manager.add_resource(resource=resource)
            assert len(manager) == 1
            stats = await manager.get_stats()
            assert stats["total_created"] == 1
            assert stats["current_count"] == 1

            retrieved = await manager.get_resource(resource_id="r1")
            assert retrieved is resource

    async def test_add_resource_closed_handler_invalid_data(
        self, manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch.object(ConcreteResourceManager, "_log")
        resource = MockResource("r1")

        async with manager:
            await manager.add_resource(resource=resource)

            event = Event(type=EventType.CONNECTION_CLOSED, data="invalid")
            resource.events.emit_nowait(event_type=EventType.CONNECTION_CLOSED, data=event.data)
            await asyncio.sleep(0.01)

            spy_logger.warning.assert_called()
            assert len(manager) == 1

    async def test_add_resource_duplicate(self, manager: ConcreteResourceManager) -> None:
        resource = MockResource("r1")

        async with manager:
            await manager.add_resource(resource=resource)
            await manager.add_resource(resource=resource)

            assert len(manager) == 1
            stats = await manager.get_stats()
            assert stats["total_created"] == 1

    async def test_add_resource_limit_reached(self, manager: ConcreteResourceManager) -> None:
        manager._max_resources = 1
        r1 = MockResource("r1")
        r2 = MockResource("r2")

        async with manager:
            await manager.add_resource(resource=r1)

            with pytest.raises(RuntimeError, match="Maximum test_item limit reached"):
                await manager.add_resource(resource=r2)

            assert len(manager) == 1
            assert r2.closed is True

    async def test_add_resource_not_activated(self, manager: ConcreteResourceManager) -> None:
        resource = MockResource("r1")

        with pytest.raises(RuntimeError, match="is not activated"):
            await manager.add_resource(resource=resource)

    async def test_add_resource_shutting_down(self, manager: ConcreteResourceManager) -> None:
        resource = MockResource("r1")

        async with manager:
            await manager.shutdown()
            with pytest.raises(RuntimeError, match="is shutting down"):
                await manager.add_resource(resource=resource)
            assert resource.closed is True

    async def test_background_task_cancellation(self, manager: ConcreteResourceManager) -> None:
        async def dummy_task() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass

        async with manager:
            task = asyncio.create_task(dummy_task())
            manager._background_tasks_to_cancel.append(task)

        assert task.cancelled() or task.done()

    async def test_background_task_cancelled_ignored(
        self, manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch.object(ConcreteResourceManager, "_log")

        async def dummy_task() -> None:
            await asyncio.sleep(0.1)

        task = asyncio.create_task(dummy_task())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        manager._on_background_task_done(task)

        spy_logger.error.assert_not_called()

    async def test_background_task_done_callback_error(
        self, manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        spy_shutdown = mocker.spy(manager, "shutdown")
        spy_logger = mocker.patch.object(ConcreteResourceManager, "_log")

        async def failing_task() -> None:
            raise ValueError("Background failure")

        async with manager:
            task = asyncio.create_task(failing_task())
            try:
                await task
            except ValueError:
                pass

            manager._on_background_task_done(task)

        assert spy_logger.error.called
        call_args = spy_logger.error.call_args
        assert call_args[0][0] == "%s background task finished unexpectedly: %s."
        assert call_args[0][1] == "Test_item"

        await asyncio.sleep(0)
        spy_shutdown.assert_called()

    async def test_cancel_background_tasks_none(self, manager: ConcreteResourceManager) -> None:
        await manager._cancel_background_tasks()

    async def test_close_all_resources_no_lock(self, manager: ConcreteResourceManager) -> None:
        await manager._close_all_resources()

        assert len(manager) == 0

    async def test_close_all_resources_stats_update(self, manager: ConcreteResourceManager) -> None:
        async with manager:
            pass

        assert manager._stats["total_closed"] == 0

    async def test_context_manager_lifecycle(self, manager: ConcreteResourceManager) -> None:
        assert manager._lock is None

        async def run_context() -> None:
            async with manager:
                assert manager._lock is not None
                assert not manager._is_shutting_down

        await run_context()

        assert manager._is_shutting_down is True

    async def test_get_all_resources(self, manager: ConcreteResourceManager) -> None:
        r1 = MockResource("r1")
        r2 = MockResource("r2")

        async with manager:
            await manager.add_resource(resource=r1)
            await manager.add_resource(resource=r2)

            all_res = await manager.get_all_resources()
            assert len(all_res) == 2
            assert r1 in all_res
            assert r2 in all_res

    async def test_get_all_resources_no_lock(self, manager: ConcreteResourceManager) -> None:
        assert await manager.get_all_resources() == []

    async def test_get_resource_no_lock(self, manager: ConcreteResourceManager) -> None:
        assert await manager.get_resource(resource_id="r1") is None

    async def test_get_stats_no_lock(self, manager: ConcreteResourceManager) -> None:
        assert await manager.get_stats() == {}

    async def test_handle_resource_closed_allowed_during_shutdown(
        self, manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        manager._is_shutting_down = True
        manager._lock = asyncio.Lock()
        manager._resources["r1"] = MockResource("r1")

        await manager._handle_resource_closed(resource_id="r1")

        assert "r1" not in manager._resources
        assert manager._stats["total_closed"] == 1

    async def test_handle_resource_closed_resource_not_found(self, manager: ConcreteResourceManager) -> None:
        manager._lock = asyncio.Lock()

        await manager._handle_resource_closed(resource_id="non_existent")

        assert manager._stats["total_closed"] == 0

    async def test_on_background_task_done_shutting_down(
        self, manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        manager._is_shutting_down = True
        spy_logger = mocker.patch.object(ConcreteResourceManager, "_log")
        mock_task = mocker.Mock(spec=asyncio.Task)

        manager._on_background_task_done(mock_task)

        spy_logger.error.assert_not_called()

    async def test_on_background_task_done_success(
        self, manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch.object(ConcreteResourceManager, "_log")
        mock_task = mocker.Mock(spec=asyncio.Task)
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = None

        manager._on_background_task_done(mock_task)

        spy_logger.error.assert_not_called()

    async def test_resource_closed_event_handling(self, manager: ConcreteResourceManager) -> None:
        resource = MockResource("r1")

        async with manager:
            await manager.add_resource(resource=resource)
            assert len(manager) == 1

            event = Event(type=EventType.CONNECTION_CLOSED, data={"test_item_id": "r1"})
            resource.events.emit_nowait(event_type=EventType.CONNECTION_CLOSED, data=event.data)

            await asyncio.sleep(0.01)

            assert len(manager) == 0
            stats = await manager.get_stats()
            assert stats["total_closed"] == 1

    async def test_resource_closed_event_mismatch_id(
        self, manager: ConcreteResourceManager, mocker: MockerFixture
    ) -> None:
        resource = MockResource("r1")
        spy_logger = mocker.patch.object(ConcreteResourceManager, "_log")

        async with manager:
            await manager.add_resource(resource=resource)

            event = Event(type=EventType.CONNECTION_CLOSED, data={"test_item_id": "wrong_id"})
            resource.events.emit_nowait(event_type=EventType.CONNECTION_CLOSED, data=event.data)

            await asyncio.sleep(0.01)

            assert len(manager) == 1
            assert spy_logger.warning.called
            args = spy_logger.warning.call_args[0]
            assert "Received close event without expected resource ID" in args[0]
            assert args[2] == "r1"

    async def test_shutdown_closes_resources(self, manager: ConcreteResourceManager) -> None:
        r1 = MockResource("r1")
        r2 = MockResource("r2")

        async with manager:
            await manager.add_resource(resource=r1)
            await manager.add_resource(resource=r2)

        assert r1.closed
        assert r2.closed
        assert len(manager) == 0
        assert manager._stats["total_closed"] == 2

    async def test_shutdown_handles_close_errors(self, manager: ConcreteResourceManager, mocker: MockerFixture) -> None:
        r1 = MockResource("r1")
        mocker.patch.object(r1, "close", side_effect=ValueError("Close failed"))
        spy_logger = mocker.patch.object(ConcreteResourceManager, "_log")

        async with manager:
            await manager.add_resource(resource=r1)

        assert spy_logger.error.called
        args = spy_logger.error.call_args[0]
        assert "Errors occurred while closing managed %ss: %s" in args[0]
        assert args[1] == "test_item"
        assert len(manager) == 0

    async def test_shutdown_idempotent(self, manager: ConcreteResourceManager) -> None:
        async with manager:
            await manager.shutdown()
            await manager.shutdown()

        assert manager._is_shutting_down
