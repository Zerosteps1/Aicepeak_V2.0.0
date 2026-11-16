using System.Text;
using System.Text.Json;
using Aicepeak.Api.Auth;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Frontend;

/// <summary>
/// Serves the built React app from wwwroot (copied there by <c>dotnet publish</c>). index.html is read once at startup,
/// its runtime config placeholder is filled from the <c>ENTRA_*</c> settings, and every page request gets that prepared
/// page from memory, so one build runs in every environment.
/// </summary>
public static class FrontendHosting {
    /// <summary>The placeholder in frontend/index.html that is replaced by the runtime config (JSON or <c>null</c>).</summary>
    public const string ConfigMarker = "null /* aicepeak-config */";

    private const string IndexFile = "index.html";

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    /// <summary>The config the frontend's MSAL needs; <c>null</c> when the Entra settings are incomplete.</summary>
    public sealed record FrontendConfig(string ClientId, string ApiScope);

    /// <summary>Static files except index.html, which is only served prepared (see <see cref="MapFrontendFallback"/>).</summary>
    public static IApplicationBuilder UseFrontendStaticFiles(this IApplicationBuilder app) =>
        app.UseWhen(context => !IsIndexFile(context.Request.Path), branch => branch.UseStaticFiles());

    /// <summary>
    /// Unknown API routes are 404; /index.html and every other path without a file extension get the prepared
    /// index.html for client-side routing. Both are catch-alls with the lowest route precedence, so explicit API routes
    /// always win. index.html is revalidated on every load (no-cache) so a redeploy is picked up; the hashed assets it
    /// references stay cacheable.
    /// </summary>
    public static IEndpointRouteBuilder MapFrontendFallback(this IEndpointRouteBuilder endpoints) {
        endpoints.Map("/api/{**path}", () => Results.NotFound());

        var page = RenderIndex(endpoints.ServiceProvider);
        IResult ServeIndex(HttpContext context) {
            if (page is null) {
                return Results.NotFound();
            }

            context.Response.Headers.CacheControl = "no-cache";
            return Results.Bytes(page, "text/html; charset=utf-8");
        }

        endpoints.MapFallback(ServeIndex).AllowAnonymous();
        endpoints.MapGet("/" + IndexFile, ServeIndex).AllowAnonymous();

        return endpoints;
    }

    /// <summary>
    /// The config as JSON for an inline script: <c>clientId</c> is <c>ENTRA_AUDIENCE</c> (one app registration for SPA
    /// and API), <c>apiScope</c> is <c>api://{ENTRA_AUDIENCE}/{ENTRA_SCOPE}</c>. The default encoder escapes &lt;, &gt;
    /// and &amp;, so a value can never close the script element.
    /// </summary>
    public static string ConfigJson(EntraOptions entra) {
        if (string.IsNullOrWhiteSpace(entra.Audience) || string.IsNullOrWhiteSpace(entra.Scope)) {
            return "null";
        }

        var audience = entra.Audience.Trim();
        return JsonSerializer.Serialize(new FrontendConfig(audience, $"api://{audience}/{entra.Scope.Trim()}"), JsonOptions);
    }

    /// <summary>index.html with the config filled in, or <c>null</c> without a built frontend.</summary>
    private static byte[]? RenderIndex(IServiceProvider services) {
        var file = services.GetRequiredService<IWebHostEnvironment>().WebRootFileProvider.GetFileInfo(IndexFile);
        if (!file.Exists) {
            return null;
        }

        using var reader = new StreamReader(file.CreateReadStream(), Encoding.UTF8);
        var html = reader.ReadToEnd();
        var config = ConfigJson(services.GetRequiredService<IOptions<EntraOptions>>().Value);

        return Encoding.UTF8.GetBytes(html.Replace(ConfigMarker, config, StringComparison.Ordinal));
    }

    private static bool IsIndexFile(PathString path) =>
        path.Equals("/" + IndexFile, StringComparison.OrdinalIgnoreCase);
}
