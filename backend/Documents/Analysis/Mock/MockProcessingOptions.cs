namespace Aicepeak.Api.Documents.Analysis.Mock;

/// <summary>
/// MOCK – AIC-02: the simulated processing time of the mock analysis, configuration key <c>MOCK_PROCESSING_STEP_MS</c>
/// (environment variable, in Development also <c>.env</c>). 0 means no waiting.
/// </summary>
public sealed class MockProcessingOptions {
    public const string StepMillisecondsKey = "MOCK_PROCESSING_STEP_MS";
    public const int DefaultStepMilliseconds = 300;

    /// <summary>Base duration of one step in milliseconds; each step takes 0.5 to 1.5 times as long.</summary>
    [ConfigurationKeyName(StepMillisecondsKey)]
    public int StepMilliseconds { get; set; } = DefaultStepMilliseconds;
}
