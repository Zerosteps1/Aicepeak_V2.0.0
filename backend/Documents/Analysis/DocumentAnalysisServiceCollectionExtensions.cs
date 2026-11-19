using Aicepeak.Api.Documents.Analysis.Mock;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Aicepeak.Api.Documents.Analysis;

public static class DocumentAnalysisServiceCollectionExtensions {
    /// <summary>
    /// Registers <see cref="DocumentAnalyzer"/>. Validation and extraction are mocks for now (AIC-02); the app logs a
    /// warning saying so at startup.
    /// </summary>
    public static IServiceCollection AddDocumentAnalysis(this IServiceCollection services, IConfiguration configuration) {
        services.AddSingleton<DocumentAnalyzer>();
        services.TryAddSingleton(TimeProvider.System);
        services.AddSingleton<IDocumentValidator, MockDocumentValidator>(); // MOCK
        services.AddSingleton<IDocumentExtractor, MockDocumentExtractor>(); // MOCK
        services.AddSingleton<MockProcessingDelay>(); // MOCK
        services.AddKeyedSingleton(MockProcessingDelay.RandomKey, Random.Shared); // MOCK
        services.AddOptions<MockProcessingOptions>() // MOCK
            .Bind(configuration)
            .Validate(options => options.StepMilliseconds >= 0, $"{MockProcessingOptions.StepMillisecondsKey} must not be negative.");
        services.AddHostedService<MockAnalysisNotice>(); // MOCK

        return services;
    }
}
