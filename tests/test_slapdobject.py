import slapd


def test_context_manager():
    with slapd.Slapd() as server:
        assert server._proc is not None
    assert server._proc is None


def test_context_manager_after_start():
    server = slapd.Slapd()
    server.start()
    assert server._proc is not None
    with server:
        assert server._proc is not None
    assert server._proc is None
