using System.Runtime.CompilerServices;
using System.Text.Json;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Documents.Analysis;
using Aicepeak.Api.Documents.Analysis.Mock;
using Aicepeak.Api.Tests.Infrastructure;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Tests.Documents;

/// <summary>
/// AC-22: the analysis is visibly mocked (resolved from DI, a startup warning), its events are deterministic, and its
/// steps take <c>MOCK_PROCESSING_STEP_MS</c> times 0.5 to 1.5. Also the guarantees of <see cref="DocumentAnalyzer"/>.
/// </summary>
public sealed class MockDocumentAnalyzerTests {
    private static readonly Document Valid = Doc("0193a5b2-0000-7000-8000-00000000000a", "Bilanz 2025.pdf");
    private static readonly Document Invalid = Doc("0193a5b2-0000-7000-8000-00000000000b", "invalid-Umsatz.xlsx");

    [Fact]
    public async Task AC22_MocksAreResolvedFromDi_AndTheStartupLogsAMockWarning() {
        await using var factory = new ApiFactory(TestSettings.Production, TestSettings.UnreachableDatabase());
        _ = factory.CreateClient();

        Assert.IsType<MockDocumentValidator>(factory.Services.GetRequiredService<IDocumentValidator>());
        Assert.IsType<MockDocumentExtractor>(factory.Services.GetRequiredService<IDocumentExtractor>());
        var warning = Assert.Single(factory.Logs.Entries, entry => entry.Category == typeof(MockAnalysisNotice).FullName);
        Assert.Equal(LogLevel.Warning, warning.Level);
        Assert.StartsWith("MOCK:", warning.Message);
        Assert.Contains("simulated", warning.Message);
    }

    [Fact]
    public async Task AC22_Validation_StepsEachDocumentThroughFiveSteps_AndFlagsNamesContainingInvalid() {
        var events = await ToListAsync(Analyzer().ValidateAsync([Valid, Invalid], TestContext.Current.CancellationToken));

        var a = Valid.Id.ToString();
        var b = Invalid.Id.ToString();
        Assert.Equal(
            [
                new(0, a, 0), new(12, a, 25), new(25, a, 50), new(37, a, 75), new(50, a, 100),
                new(50, b, 0), new(62, b, 25), new(75, b, 50), new(87, b, 75), new(100, b, 100, MockDocumentValidator.InvalidError),
            ],
            events);
    }

    [Fact]
    public async Task AC22_Extraction_Reads3To12PagesPerDocument_TwoPositionsPerPage_Deterministically() {
        var first = await ToListAsync(Analyzer().ExtractAsync([Valid, Invalid], TestContext.Current.CancellationToken));
        var second = await ToListAsync(Analyzer(stepMilliseconds: 1, seed: 7).ExtractAsync([Valid, Invalid], TestContext.Current.CancellationToken));

        Assert.Equal(JsonSerializer.Serialize(first), JsonSerializer.Serialize(second));
        var pages = new[] { Valid, Invalid }.Select(MockDocumentExtractor.PageCount).ToArray();
        Assert.All(pages, count => Assert.InRange(count, 3, 12));
        Assert.Equal(pages.Sum() + 2, first.Count);
        var positions = 0;
        foreach (var (document, count) in new[] { Valid, Invalid }.Zip(pages)) {
            var steps = first.Where(item => item.Document == document.Id.ToString()).ToList();
            Assert.Equal(Enumerable.Range(0, count + 1), steps.Select(step => step.PagesRead!.Value));
            Assert.All(steps, step => Assert.Equal(count, step.Pages));
            Assert.Null(steps[0].Position);
            foreach (var step in steps.Skip(1)) {
                positions += MockDocumentExtractor.PositionsPerPage;
                Assert.Equal(positions, step.Positions);
                Assert.Equal(step.PagesRead, step.Position!.Page);
                Assert.Equal(document.Name, step.Position.Source);
            }
        }

        Assert.Equal(100, first[^1].DocumentProgress);
    }

    [Fact]
    public async Task AC22_OverallProgress_Is100ExactlyOnce_InTheLastEvent() {
        var ct = TestContext.Current.CancellationToken;
        foreach (var events in new[] {
                     await ToListAsync(Analyzer().ValidateAsync([Valid, Invalid, Valid], ct)),
                     await ToListAsync(Analyzer().ExtractAsync([Invalid, Valid], ct)),
                 }) {
            Assert.Equal(100, events[^1].OverallProgress);
            Assert.All(events[..^1], item => Assert.InRange(item.OverallProgress, 0, 99));
            Assert.True(events.Zip(events.Skip(1)).All(pair => pair.First.OverallProgress <= pair.Second.OverallProgress));
        }
    }

    [Fact]
    public async Task AC22_NoDocuments_IsASingleFinalEvent() {
        var ct = TestContext.Current.CancellationToken;

        Assert.Equal([new DocumentProgressEvent(100, "")], await ToListAsync(Analyzer().ValidateAsync([], ct)));
        Assert.Equal([new DocumentProgressEvent(100, "")], await ToListAsync(Analyzer().ExtractAsync([], ct)));
    }

    [Fact]
    public async Task FailingValidator_EndsTheRunWithAnErrorForTheRun() {
        var analyzer = new DocumentAnalyzer(new FailingValidator(), new MockDocumentExtractor(Delay(0)), NullLogger<DocumentAnalyzer>.Instance);

        var events = await ToListAsync(analyzer.ValidateAsync([Valid, Invalid], TestContext.Current.CancellationToken));

        Assert.Equal(
            [new DocumentProgressEvent(0, Valid.Id.ToString(), 0), new DocumentProgressEvent(100, "", Error: DocumentAnalyzer.RunFailedError)],
            events);
    }

    [Fact]
    public void AC22_StepDelay_IsTheSettingTimesHalfToOneAndAHalf() {
        var delay = Delay(300, seed: 42);

        var samples = Enumerable.Range(0, 1000).Select(_ => delay.Next().TotalMilliseconds).ToList();

        Assert.All(samples, sample => Assert.InRange(sample, 150, 450));
        Assert.True(samples.Min() < 180 && samples.Max() > 420, "The factor should spread over 0.5 to 1.5.");
    }

    [Fact]
    public void AC22_StepDelayZero_DoesNotWait_AndTheDefaultIs300() {
        var delay = Delay(0);

        Assert.Equal(TimeSpan.Zero, delay.Next());
        Assert.True(delay.WaitAsync(TestContext.Current.CancellationToken).IsCompletedSuccessfully);
        Assert.Equal(300, new MockProcessingOptions().StepMilliseconds);
    }

    private static DocumentAnalyzer Analyzer(int stepMilliseconds = 0, int seed = 1) {
        var delay = Delay(stepMilliseconds, seed);
        return new DocumentAnalyzer(new MockDocumentValidator(delay), new MockDocumentExtractor(delay), NullLogger<DocumentAnalyzer>.Instance);
    }

    private static MockProcessingDelay Delay(int stepMilliseconds, int seed = 1) =>
        new(Options.Create(new MockProcessingOptions { StepMilliseconds = stepMilliseconds }), new Random(seed), TimeProvider.System);

    private static Document Doc(string id, string name) => new() {
        Id = new Guid(id),
        ProjectId = new Guid("0193a5b2-0000-7000-8000-000000000001"),
        BlobName = $"0193a5b2-0000-7000-8000-000000000001/{id}",
        Name = name,
        Size = 1234,
        ContentType = "application/pdf",
        Sha256 = new byte[32],
        CreatedAt = DateTimeOffset.UnixEpoch,
    };

    private static async Task<List<DocumentProgressEvent>> ToListAsync(IAsyncEnumerable<DocumentProgressEvent> events) {
        var list = new List<DocumentProgressEvent>();
        await foreach (var item in events) {
            list.Add(item);
        }

        return list;
    }

    /// <summary>Starts the first document, then fails.</summary>
    private sealed class FailingValidator : IDocumentValidator {
        public async IAsyncEnumerable<ValidationStep> ValidateAsync(Document document, [EnumeratorCancellation] CancellationToken cancellationToken) {
            yield return new ValidationStep(0);
            await Task.Yield();
            throw new InvalidOperationException("validator broke");
        }
    }
}
