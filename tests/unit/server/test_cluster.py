"""Unit tests for the pywebtransport.server.cluster module."""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ServerConfig
from pywebtransport.server import ServerCluster, WebTransportServer


class TestServerCluster:
    @pytest.fixture
    def server_configs(self, mocker: MockerFixture) -> list[ServerConfig]:
        mocker.patch("pywebtransport.config.ServerConfig.validate")
        return [
            ServerConfig(bind_port=8001, certfile="c1.pem", keyfile="k1.pem"),
            ServerConfig(bind_port=8002, certfile="c2.pem", keyfile="k2.pem"),
        ]

    @pytest.fixture
    def mock_webtransport_server_class(self, mocker: MockerFixture) -> Any:
        mock_server_class = mocker.patch("pywebtransport.server.cluster.WebTransportServer")

        def new_server_instance(*args, **kwargs):
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
                instance.local_address = ("127.0.0.1", kwargs["config"].bind_port)
            return instance

        mock_server_class.side_effect = new_server_instance
        return mock_server_class

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
    async def test_start_and_stop_all(
        self,
        server_configs: list[ServerConfig],
        mock_webtransport_server_class: Any,
    ) -> None:
        cluster = ServerCluster(configs=server_configs)

        await cluster.start_all()
        assert cluster.is_running
        assert len(cluster._servers) == 2
        for server in cluster._servers:
            server.listen.assert_awaited_once()

        servers_to_stop = cluster._servers
        await cluster.stop_all()
        assert not cluster.is_running
        assert not cluster._servers
        for server in servers_to_stop:
            server.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_and_stop_idempotency(
        self, server_configs: list[ServerConfig], mock_webtransport_server_class: Any
    ) -> None:
        cluster = ServerCluster(configs=server_configs)

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
        mock_server_ok = mocker.create_autospec(WebTransportServer, instance=True, spec_set=True)
        mock_server_ok.__aenter__ = mocker.AsyncMock(return_value=mock_server_ok)
        mock_server_ok.listen = mocker.AsyncMock()
        mock_server_ok.close = mocker.AsyncMock()
        mock_server_fail = mocker.create_autospec(WebTransportServer, instance=True, spec_set=True)
        mock_server_fail.__aenter__ = mocker.AsyncMock(return_value=mock_server_fail)
        mock_server_fail.listen = mocker.AsyncMock(side_effect=ValueError("Listen failed"))
        mock_server_fail.close = mocker.AsyncMock()
        mock_webtransport_server_class.side_effect = [mock_server_ok, mock_server_fail]
        cluster = ServerCluster(configs=server_configs)

        with pytest.raises(ValueError, match="Listen failed"):
            await cluster.start_all()

        assert not cluster.is_running
        assert not cluster._servers
        mock_server_ok.close.assert_awaited_once()
        mock_server_fail.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_all_with_only_failures(
        self, server_configs: list[ServerConfig], mocker: MockerFixture
    ) -> None:
        mocker.patch.object(
            ServerCluster,
            "_create_and_start_server",
            side_effect=ValueError("Failed to create"),
        )
        cluster = ServerCluster(configs=server_configs)

        with pytest.raises(ValueError, match="Failed to create"):
            await cluster.start_all()

        assert not cluster.is_running
        assert not cluster._servers

    @pytest.mark.asyncio
    async def test_stop_all_on_non_running_cluster(
        self, server_configs: list[ServerConfig], mocker: MockerFixture
    ) -> None:
        cluster = ServerCluster(configs=server_configs)
        mock_close = mocker.AsyncMock()
        cluster._servers = [mocker.MagicMock(close=mock_close)]

        await cluster.stop_all()

        mock_close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_server(self, server_configs: list[ServerConfig], mock_webtransport_server_class: Any) -> None:
        cluster = ServerCluster(configs=server_configs)
        new_config = ServerConfig(bind_port=8003, certfile="c3.pem", keyfile="k3.pem")

        result = await cluster.add_server(new_config)
        assert result is None
        assert len(cluster._configs) == 3

        await cluster.start_all()
        assert len(cluster._servers) == 3

        another_config = ServerConfig(bind_port=8004, certfile="c4.pem", keyfile="k4.pem")
        new_server = await cluster.add_server(another_config)
        assert new_server is not None
        assert len(cluster._servers) == 4
        new_server.listen.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_server_failure_on_creation(
        self,
        server_configs: list[ServerConfig],
        mocker: MockerFixture,
        mock_webtransport_server_class: Any,
    ) -> None:
        cluster = ServerCluster(configs=[server_configs[0]])
        await cluster.start_all()
        assert await cluster.get_server_count() == 1

        mocker.patch.object(
            cluster,
            "_create_and_start_server",
            side_effect=IOError("Failed to bind socket"),
        )
        new_config = ServerConfig(bind_port=8003, certfile="c3.pem", keyfile="k3.pem")
        result = await cluster.add_server(new_config)

        assert result is None
        assert await cluster.get_server_count() == 1

    @pytest.mark.asyncio
    async def test_remove_server(self, server_configs: list[ServerConfig], mock_webtransport_server_class: Any) -> None:
        cluster = ServerCluster(configs=server_configs)
        await cluster.start_all()

        initial_servers = cluster._servers.copy()
        assert len(initial_servers) == 2

        removed = await cluster.remove_server(host="127.0.0.1", port=8001)
        assert removed is True
        assert len(cluster._servers) == 1
        assert cluster._servers[0] is initial_servers[1]
        initial_servers[0].close.assert_awaited_once()

        removed = await cluster.remove_server(host="127.0.0.1", port=9999)
        assert removed is False
        assert len(cluster._servers) == 1

    @pytest.mark.asyncio
    async def test_get_servers_and_count(
        self, server_configs: list[ServerConfig], mock_webtransport_server_class: Any
    ) -> None:
        cluster = ServerCluster(configs=server_configs)
        assert await cluster.get_server_count() == 0

        await cluster.start_all()
        assert await cluster.get_server_count() == 2

        servers_copy = await cluster.get_servers()
        assert len(servers_copy) == 2
        assert servers_copy is not cluster._servers

    @pytest.mark.asyncio
    async def test_get_cluster_stats(
        self, server_configs: list[ServerConfig], mock_webtransport_server_class: Any
    ) -> None:
        cluster = ServerCluster(configs=server_configs)

        assert await cluster.get_cluster_stats() == {}

        await cluster.start_all()
        stats = await cluster.get_cluster_stats()

        assert stats["server_count"] == 2
        assert stats["total_connections_accepted"] == 2
        assert stats["total_connections_rejected"] == 2
        assert stats["total_connections_active"] == 2
        assert stats["total_sessions_active"] == 2
