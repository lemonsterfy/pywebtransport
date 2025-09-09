"""Unit tests for the pywebtransport.server.cluster module."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ServerConfig, ServerError
from pywebtransport.server import ServerCluster, WebTransportServer


class TestServerCluster:
    @pytest.fixture
    async def cluster(
        self, server_configs: list[ServerConfig], mock_webtransport_server_class: Any
    ) -> AsyncGenerator[ServerCluster, None]:
        cluster_instance = ServerCluster(configs=server_configs)
        cluster_instance._lock = asyncio.Lock()
        try:
            yield cluster_instance
        finally:
            if cluster_instance.is_running:
                try:
                    await cluster_instance.stop_all()
                except ExceptionGroup:
                    pass

    @pytest.fixture
    def mock_webtransport_server_class(self, mocker: MockerFixture) -> Any:
        mock_server_class = mocker.patch("pywebtransport.server.cluster.WebTransportServer")

        def new_server_instance(*args: Any, **kwargs: Any) -> Any:
            instance = mocker.create_autospec(WebTransportServer, instance=True)
            instance.__aenter__ = mocker.AsyncMock(return_value=instance)
            instance.listen = mocker.AsyncMock()
            instance.close = mocker.AsyncMock()
            instance.get_server_stats = mocker.AsyncMock(
                return_value={
                    "connections_accepted": 1,
                    "connections_rejected": 1,
                    "connections": {"active": 1},
                    "sessions": {"active": 1},
                }
            )
            if "config" in kwargs and hasattr(kwargs["config"], "bind_port"):
                local_address = ("127.0.0.1", kwargs["config"].bind_port)
                type(instance).local_address = mocker.PropertyMock(return_value=local_address)
            return instance

        mock_server_class.side_effect = new_server_instance
        return mock_server_class

    @pytest.fixture
    def server_configs(self, mocker: MockerFixture) -> list[ServerConfig]:
        mocker.patch("pywebtransport.config.ServerConfig.validate")
        return [
            ServerConfig(bind_port=8001, certfile="c1.pem", keyfile="k1.pem"),
            ServerConfig(bind_port=8002, certfile="c2.pem", keyfile="k2.pem"),
        ]

    def test_init(self, server_configs: list[ServerConfig]) -> None:
        cluster = ServerCluster(configs=server_configs)

        assert cluster._configs is server_configs
        assert not cluster.is_running
        assert not cluster._servers

    @pytest.mark.asyncio
    async def test_async_context_manager(self, server_configs: list[ServerConfig], mocker: MockerFixture) -> None:
        cluster = ServerCluster(configs=server_configs)
        mock_start = mocker.patch.object(cluster, "start_all", new_callable=mocker.AsyncMock)
        mock_stop = mocker.patch.object(cluster, "stop_all", new_callable=mocker.AsyncMock)

        async with cluster:
            mock_start.assert_awaited_once()
            mock_stop.assert_not_called()

        mock_stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_and_stop_all(self, cluster: ServerCluster) -> None:
        await cluster.start_all()

        assert cluster.is_running
        assert len(cluster._servers) == 2
        for server in cluster._servers:
            cast(Any, server.listen).assert_awaited_once()

        servers_to_stop = cluster._servers
        await cluster.stop_all()

        assert not cluster.is_running
        assert not cluster._servers  # type: ignore [unreachable]
        for server in servers_to_stop:
            cast(Any, server.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_and_stop_idempotency(self, cluster: ServerCluster) -> None:
        await cluster.start_all()
        assert len(cluster._servers) == 2

        await cluster.start_all()
        assert len(cluster._servers) == 2

        await cluster.stop_all()
        assert not cluster._servers

        await cluster.stop_all()
        assert not cluster._servers

    @pytest.mark.asyncio
    async def test_start_all_failure(
        self,
        server_configs: list[ServerConfig],
        mock_webtransport_server_class: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_server_fail = mocker.create_autospec(WebTransportServer, instance=True, spec_set=True)
        mock_server_fail.__aenter__ = mocker.AsyncMock(return_value=mock_server_fail)
        mock_server_fail.listen = mocker.AsyncMock(side_effect=ValueError("Listen failed"))
        mock_server_fail.close = mocker.AsyncMock()
        mock_server_ok = mocker.create_autospec(WebTransportServer, instance=True, spec_set=True)
        mock_server_ok.__aenter__ = mocker.AsyncMock(return_value=mock_server_ok)
        mock_server_ok.listen = mocker.AsyncMock()
        mock_server_ok.close = mocker.AsyncMock()
        mock_webtransport_server_class.side_effect = [mock_server_fail, mock_server_ok]
        cluster = ServerCluster(configs=server_configs)
        cluster._lock = asyncio.Lock()

        try:
            await cluster.start_all()
            pytest.fail("Should have raised an exception.")
        except ExceptionGroup as exc_info:
            match, _ = exc_info.split(ValueError)
            assert match is not None
            assert len(match.exceptions) == 1
            assert str(match.exceptions[0]) == "Listen failed"
        except ValueError as e:
            assert str(e) == "Listen failed"

        assert not cluster.is_running
        assert not cluster._servers
        cast(Any, mock_server_ok.close).assert_awaited_once()
        cast(Any, mock_server_fail.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_all_failure_during_cleanup(
        self, server_configs: list[ServerConfig], mock_webtransport_server_class: Any, mocker: MockerFixture
    ) -> None:
        mock_server_fail = mocker.create_autospec(WebTransportServer, instance=True, spec_set=True)
        mock_server_fail.listen = mocker.AsyncMock(side_effect=ValueError("Listen failed"))
        mock_server_fail.close = mocker.AsyncMock()
        mock_server_ok = mocker.create_autospec(WebTransportServer, instance=True, spec_set=True)
        mock_server_ok.listen = mocker.AsyncMock()
        mock_server_ok.close = mocker.AsyncMock(side_effect=IOError("Cleanup failed"))
        mock_webtransport_server_class.side_effect = [mock_server_fail, mock_server_ok]
        cluster = ServerCluster(configs=server_configs)
        cluster._lock = asyncio.Lock()

        try:
            await cluster.start_all()
            pytest.fail("Should have raised an exception.")
        except ExceptionGroup:
            pass
        except ValueError:
            pass

    @pytest.mark.asyncio
    async def test_stop_all_failure(self, cluster: ServerCluster) -> None:
        await cluster.start_all()
        server_to_fail = cluster._servers[0]
        cast(Any, server_to_fail.close).side_effect = ValueError("Close failed")

        with pytest.raises(ExceptionGroup):
            await cluster.stop_all()

        assert not cluster.is_running
        assert not cluster._servers

    @pytest.mark.asyncio
    async def test_add_server(self, cluster: ServerCluster, server_configs: list[ServerConfig]) -> None:
        new_config = ServerConfig(bind_port=8003, certfile="c3.pem", keyfile="k3.pem")
        result = await cluster.add_server(config=new_config)
        assert result is None
        assert len(cluster._configs) == 3

        await cluster.start_all()
        assert len(cluster._servers) == 3

        another_config = ServerConfig(bind_port=8004, certfile="c4.pem", keyfile="k4.pem")
        new_server = await cluster.add_server(config=another_config)
        assert new_server is not None
        assert len(cluster._servers) == 4
        cast(Any, new_server.listen).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_server_race_condition_on_stop(
        self, cluster: ServerCluster, mocker: MockerFixture, mock_webtransport_server_class: Any
    ) -> None:
        await cluster.start_all()
        new_config = ServerConfig(bind_port=8003, certfile="c3.pem", keyfile="k3.pem")
        creation_started = asyncio.Event()
        original_create = cluster._create_and_start_server
        created_server_ref = []

        async def controlled_creation(*args: Any, **kwargs: Any) -> WebTransportServer:
            server = await original_create(**kwargs)
            created_server_ref.append(server)
            creation_started.set()
            await asyncio.sleep(0.01)
            return server

        mocker.patch.object(cluster, "_create_and_start_server", side_effect=controlled_creation)

        async def stop_cluster_concurrently() -> None:
            await creation_started.wait()
            assert cluster._lock is not None
            async with cluster._lock:
                cluster._running = False

        add_task = asyncio.create_task(cluster.add_server(config=new_config))
        stop_task = asyncio.create_task(stop_cluster_concurrently())

        result = await add_task
        await stop_task

        assert result is None
        assert len(created_server_ref) == 1
        cast(Any, created_server_ref[0].close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_server_failure_on_creation(self, cluster: ServerCluster, mocker: MockerFixture) -> None:
        await cluster.start_all()
        initial_count = await cluster.get_server_count()
        mocker.patch.object(
            cluster,
            "_create_and_start_server",
            side_effect=IOError("Failed to bind socket"),
        )
        new_config = ServerConfig(bind_port=8003, certfile="c3.pem", keyfile="k3.pem")

        result = await cluster.add_server(config=new_config)

        assert result is None
        assert await cluster.get_server_count() == initial_count

    @pytest.mark.asyncio
    async def test_remove_server(self, cluster: ServerCluster) -> None:
        await cluster.start_all()
        initial_servers = cluster._servers.copy()
        assert len(initial_servers) == 2

        removed = await cluster.remove_server(host="127.0.0.1", port=8001)
        assert removed is True
        assert len(cluster._servers) == 1
        assert cluster._servers[0] is initial_servers[1]
        cast(Any, initial_servers[0].close).assert_awaited_once()

        removed = await cluster.remove_server(host="127.0.0.1", port=9999)
        assert removed is False
        assert len(cluster._servers) == 1

    @pytest.mark.asyncio
    async def test_get_servers_and_count(self, cluster: ServerCluster) -> None:
        assert await cluster.get_server_count() == 0

        await cluster.start_all()
        assert await cluster.get_server_count() == 2
        servers_copy = await cluster.get_servers()
        assert len(servers_copy) == 2
        assert servers_copy is not cluster._servers

    @pytest.mark.asyncio
    async def test_get_cluster_stats(self, cluster: ServerCluster) -> None:
        assert await cluster.get_cluster_stats() == {}

        await cluster.start_all()
        stats = await cluster.get_cluster_stats()

        assert stats["server_count"] == 2
        assert stats["total_connections_accepted"] == 2
        assert stats["total_connections_rejected"] == 2
        assert stats["total_connections_active"] == 2
        assert stats["total_sessions_active"] == 2

    @pytest.mark.asyncio
    async def test_get_cluster_stats_with_partial_failure(self, cluster: ServerCluster) -> None:
        await cluster.start_all()
        server_to_fail = cluster._servers[0]
        cast(Any, server_to_fail.get_server_stats).side_effect = ValueError("Stats failed")

        with pytest.raises(ExceptionGroup):
            await cluster.get_cluster_stats()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, method_args",
        [
            ("start_all", {}),
            ("stop_all", {}),
            ("add_server", {"config": ServerConfig()}),
            ("remove_server", {"host": "localhost", "port": 8000}),
            ("get_cluster_stats", {}),
            ("get_server_count", {}),
            ("get_servers", {}),
        ],
    )
    async def test_public_methods_raise_if_not_activated(
        self, server_configs: list[ServerConfig], method_name: str, method_args: Any
    ) -> None:
        cluster = ServerCluster(configs=server_configs)
        method = getattr(cluster, method_name)

        with pytest.raises(ServerError, match="ServerCluster has not been activated"):
            await method(**method_args)
