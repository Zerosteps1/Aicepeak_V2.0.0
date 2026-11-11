using System.Net;
using System.Net.Sockets;

namespace Aicepeak.Api.Tests.Infrastructure;

public static class TestSettings {
    public const string Development = "Development";
    public const string Production = "Production";

    /// <summary>
    /// All three database keys, always set, so a developer's .env or shell variables never leak into a test.
    /// An empty string means "missing".
    /// </summary>
    public static Dictionary<string, string?> Database(string conStr, string user, string password) => new() {
        ["DB_CON_STR"] = conStr,
        ["DB_USR"] = user,
        ["DB_PWD"] = password,
    };

    /// <summary>Settings pointing at a local port nobody listens on, so connecting fails fast.</summary>
    public static Dictionary<string, string?> UnreachableDatabase(string password = "postgres") =>
        Database($"Host=127.0.0.1;Port={GetClosedPort()};Database=aicepeak;Timeout=3", "postgres", password);

    private static int GetClosedPort() {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }
}
