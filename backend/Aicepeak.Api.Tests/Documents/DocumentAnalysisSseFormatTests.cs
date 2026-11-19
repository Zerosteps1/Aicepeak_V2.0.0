using System.Text;
using Aicepeak.Api.Documents.Analysis;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;

namespace Aicepeak.Api.Tests.Documents;

/// <summary>
/// The SSE wire format of <see cref="DocumentProgressEvent"/>: default event type (<c>message</c>), one camelCase JSON
/// object per <c>data:</c> line, null fields left out.
/// </summary>
public sealed class DocumentAnalysisSseFormatTests {
    [Fact]
    public async Task Events_AreCamelCaseJsonDataLines_WithoutNullFields() {
        var (contentType, body) = await WriteAsync(
            new DocumentProgressEvent(0, "d1", 0),
            new DocumentProgressEvent(50, "d1", 100, "Mock: kein Finanzbericht erkannt."),
            new DocumentProgressEvent(
                75, "d2", 50, Pages: 4, PagesRead: 2, Positions: 6, Position: new ExtractedPosition("Umsatzerlöse", 12_500.5m, "2025", "a.pdf", 2)),
            new DocumentProgressEvent(100, ""));

        Assert.Equal("text/event-stream", contentType);
        Assert.Equal(
            """
            data: {"overallProgress":0,"document":"d1","documentProgress":0}

            data: {"overallProgress":50,"document":"d1","documentProgress":100,"error":"Mock: kein Finanzbericht erkannt."}

            data: {"overallProgress":75,"document":"d2","documentProgress":50,"pages":4,"pagesRead":2,"positions":6,"position":{"name":"Umsatzerlöse","value":12500.5,"period":"2025","source":"a.pdf","page":2}}

            data: {"overallProgress":100,"document":""}


            """.ReplaceLineEndings("\n"),
            body);
    }

    private static async Task<(string? ContentType, string Body)> WriteAsync(params DocumentProgressEvent[] events) {
        var context = new DefaultHttpContext { RequestServices = new ServiceCollection().AddOptions().BuildServiceProvider() };
        using var body = new MemoryStream();
        context.Response.Body = body;

        await TypedResults.ServerSentEvents(ToAsync(events)).ExecuteAsync(context);

        return (context.Response.ContentType, Encoding.UTF8.GetString(body.ToArray()));
    }

    private static async IAsyncEnumerable<DocumentProgressEvent> ToAsync(IEnumerable<DocumentProgressEvent> events) {
        foreach (var item in events) {
            await Task.Yield();
            yield return item;
        }
    }
}
