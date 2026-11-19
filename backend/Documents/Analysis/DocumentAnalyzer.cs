using System.Runtime.CompilerServices;
using Aicepeak.Api.Data.Entities;

namespace Aicepeak.Api.Documents.Analysis;

/// <summary>
/// Analyses documents: validation (<see cref="IDocumentValidator"/>) and extraction (<see cref="IDocumentExtractor"/>),
/// one document after the other, as a stream of <see cref="DocumentProgressEvent"/>s. Knows documents only, nothing
/// of projects. Guarantees for both streams: <c>overallProgress</c> is below 100 until the last event, which has 100
/// and comes exactly once; without documents that is the single event <c>{overallProgress: 100, document: ""}</c>; a
/// failure ends the run with <c>{overallProgress: 100, document: "", error}</c>.
/// </summary>
public sealed class DocumentAnalyzer(IDocumentValidator validator, IDocumentExtractor extractor, ILogger<DocumentAnalyzer> logger) {
    public const string RunFailedError = "Die Analyse ist fehlgeschlagen.";

    public IAsyncEnumerable<DocumentProgressEvent> ValidateAsync(IReadOnlyList<Document> documents, CancellationToken cancellationToken) =>
        RunAsync(documents, validator.ValidateAsync, ValidationEvent, cancellationToken);

    public IAsyncEnumerable<DocumentProgressEvent> ExtractAsync(IReadOnlyList<Document> documents, CancellationToken cancellationToken) {
        var positions = 0;
        return RunAsync(documents, extractor.ExtractAsync, ExtractionEvent, cancellationToken);

        (int, DocumentProgressEvent) ExtractionEvent(Document document, ExtractionStep step) {
            positions += step.NewPositions;
            var progress = step.Pages > 0 ? step.PagesRead * 100 / step.Pages : 100;
            return (progress, new DocumentProgressEvent(
                0, document.Id.ToString("D"), progress, Pages: step.Pages, PagesRead: step.PagesRead, Positions: positions,
                Position: step.Position));
        }
    }

    private static (int, DocumentProgressEvent) ValidationEvent(Document document, ValidationStep step) =>
        (step.Progress, new DocumentProgressEvent(0, document.Id.ToString("D"), step.Progress, step.Error));

    /// <summary>
    /// Runs <paramref name="analyze"/> for each document and sets <c>overallProgress</c>: the mean document progress,
    /// at most 99 until the last event, which is held back until the run ends and then gets 100.
    /// </summary>
    private async IAsyncEnumerable<DocumentProgressEvent> RunAsync<TStep>(
        IReadOnlyList<Document> documents,
        Func<Document, CancellationToken, IAsyncEnumerable<TStep>> analyze,
        Func<Document, TStep, (int Progress, DocumentProgressEvent Event)> toEvent,
        [EnumeratorCancellation] CancellationToken cancellationToken) {
        var progress = new int[documents.Count];
        DocumentProgressEvent? pending = null;
        var failed = false;
        for (var index = 0; index < documents.Count && !failed; index++) {
            await using var steps = analyze(documents[index], cancellationToken).GetAsyncEnumerator(cancellationToken);
            while (true) {
                try {
                    if (!await steps.MoveNextAsync()) {
                        break;
                    }
                } catch (Exception exception) when (exception is not OperationCanceledException) {
                    logger.LogError(exception, "Analysing a document failed.");
                    failed = true;
                    break;
                }

                var (documentProgress, next) = toEvent(documents[index], steps.Current);
                progress[index] = Math.Clamp(documentProgress, 0, 100);
                if (pending is not null) {
                    yield return pending;
                }

                pending = next with { OverallProgress = Math.Min(99, progress.Sum() / documents.Count) };
            }
        }

        if (failed) {
            if (pending is not null) {
                yield return pending;
            }

            yield return new DocumentProgressEvent(100, "", Error: RunFailedError);
        } else {
            yield return pending is null ? new DocumentProgressEvent(100, "") : pending with { OverallProgress = 100 };
        }
    }
}
