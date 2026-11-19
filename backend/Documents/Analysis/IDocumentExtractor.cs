using Aicepeak.Api.Data.Entities;

namespace Aicepeak.Api.Documents.Analysis;

/// <summary>Extracts financial positions from a document, page by page. Part of <see cref="DocumentAnalyzer"/>.</summary>
public interface IDocumentExtractor {
    IAsyncEnumerable<ExtractionStep> ExtractAsync(Document document, CancellationToken cancellationToken);
}

/// <param name="Pages">Pages of the document.</param>
/// <param name="PagesRead">Pages read so far.</param>
/// <param name="NewPositions">Positions found since the previous step.</param>
/// <param name="Position">A position found in this step, if any.</param>
public sealed record ExtractionStep(int Pages, int PagesRead, int NewPositions = 0, ExtractedPosition? Position = null);
