using System.Runtime.CompilerServices;
using Aicepeak.Api.Data.Entities;

namespace Aicepeak.Api.Documents.Analysis.Mock;

/// <summary>
/// MOCK – AIC-02: simulates validation without reading the file. Every document goes through progress 0, 25, 50, 75 and
/// 100; a document whose name contains <c>invalid</c> (any case) ends with <see cref="InvalidError"/>. Each step after
/// the first waits <see cref="MockProcessingDelay"/>.
/// </summary>
public sealed class MockDocumentValidator(MockProcessingDelay delay) : IDocumentValidator {
    public const string InvalidError = "Mock: kein Finanzbericht erkannt.";

    public async IAsyncEnumerable<ValidationStep> ValidateAsync(
        Document document, [EnumeratorCancellation] CancellationToken cancellationToken) {
        var invalid = document.Name.Contains("invalid", StringComparison.OrdinalIgnoreCase);
        for (var progress = 0; progress <= 100; progress += 25) {
            if (progress > 0) {
                await delay.WaitAsync(cancellationToken);
            }

            yield return new ValidationStep(progress, invalid && progress == 100 ? InvalidError : null);
        }
    }
}
