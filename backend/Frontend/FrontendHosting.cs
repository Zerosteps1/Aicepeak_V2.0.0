namespace Aicepeak.Api.Frontend;

/// <summary>Serves the built React app from wwwroot (copied there by <c>dotnet publish</c>).</summary>
public static class FrontendHosting {
    private const string IndexFile = "index.html";

    // index.html is revalidated on every load so a redeploy is picked up; the hashed assets it references stay cacheable.
    private static readonly StaticFileOptions StaticFileOptions = new() {
        OnPrepareResponse = context => {
            if (context.File.Name == IndexFile) {
                context.Context.Response.Headers.CacheControl = "no-cache";
            }
        },
    };

    public static IApplicationBuilder UseFrontendStaticFiles(this IApplicationBuilder app) =>
        app.UseStaticFiles(StaticFileOptions);

    /// <summary>
    /// Unknown API routes are 404; every other path without a file extension falls back to index.html
    /// for client-side routing. Both are catch-alls with the lowest route precedence, so explicit API routes always win.
    /// </summary>
    public static IEndpointRouteBuilder MapFrontendFallback(this IEndpointRouteBuilder endpoints) {
        endpoints.Map("/api/{**path}", () => Results.NotFound());
        endpoints.MapFallbackToFile(IndexFile, StaticFileOptions).AllowAnonymous();

        return endpoints;
    }
}
