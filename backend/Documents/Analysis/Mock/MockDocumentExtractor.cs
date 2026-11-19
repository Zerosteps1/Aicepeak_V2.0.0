using System.Runtime.CompilerServices;
using Aicepeak.Api.Data.Entities;

namespace Aicepeak.Api.Documents.Analysis.Mock;

/// <summary>
/// MOCK – AIC-02: simulates extraction without reading the file. A document has <see cref="PageCount"/> pages (3 to 12,
/// derived from its ID); the first step reports the page count, then each page read finds
/// <see cref="PositionsPerPage"/> positions and reports one sample position. Each page waits
/// <see cref="MockProcessingDelay"/>. The same document always gives the same steps.
/// </summary>
public sealed class MockDocumentExtractor(MockProcessingDelay delay) : IDocumentExtractor {
    public const int PositionsPerPage = 2;

    private static readonly string[] SampleNames = [
        "Umsatzerlöse", "Materialaufwand", "Personalaufwand", "Energiekosten", "Abschreibungen", "Sonstige betriebliche Aufwendungen",
    ];

    public static int PageCount(Document document) => 3 + document.Id.ToByteArray().Sum(value => value) % 10;

    public async IAsyncEnumerable<ExtractionStep> ExtractAsync(
        Document document, [EnumeratorCancellation] CancellationToken cancellationToken) {
        var pages = PageCount(document);
        yield return new ExtractionStep(pages, 0);
        for (var page = 1; page <= pages; page++) {
            await delay.WaitAsync(cancellationToken);
            yield return new ExtractionStep(pages, page, PositionsPerPage, SamplePosition(document, page));
        }
    }

    private static ExtractedPosition SamplePosition(Document document, int page) => new(
        SampleNames[(page - 1) % SampleNames.Length], 10_000m + 1_250.5m * page, "2025", document.Name, page);
}
