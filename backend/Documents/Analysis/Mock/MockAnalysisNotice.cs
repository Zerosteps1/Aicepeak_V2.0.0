namespace Aicepeak.Api.Documents.Analysis.Mock;

/// <summary>MOCK – AIC-02: logs a warning at startup that document analysis is simulated, so no environment mistakes it for real.</summary>
public sealed class MockAnalysisNotice(ILogger<MockAnalysisNotice> logger) : IHostedService {
    public const string Message =
        "MOCK: document validation and extraction are simulated (AIC-02); documents are not analysed and all results are made up.";

    public Task StartAsync(CancellationToken cancellationToken) {
        logger.LogWarning(Message);
        return Task.CompletedTask;
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
