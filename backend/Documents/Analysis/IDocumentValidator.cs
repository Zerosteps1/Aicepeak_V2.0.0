using Aicepeak.Api.Data.Entities;

namespace Aicepeak.Api.Documents.Analysis;

/// <summary>Checks whether a document is usable (e.g. a financial report). Part of <see cref="DocumentAnalyzer"/>.</summary>
public interface IDocumentValidator {
    /// <summary>The steps of validating one document, progress 0 to 100; an error marks the document invalid.</summary>
    IAsyncEnumerable<ValidationStep> ValidateAsync(Document document, CancellationToken cancellationToken);
}

/// <param name="Progress">Progress of this document, 0 to 100.</param>
/// <param name="Error">A short reason shown to the user when the document is invalid.</param>
public sealed record ValidationStep(int Progress, string? Error = null);
