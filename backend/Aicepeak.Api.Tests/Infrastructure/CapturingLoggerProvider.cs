using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;

namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>Records every log entry of the hosted API (category, level, formatted message, exception).</summary>
public sealed class CapturingLoggerProvider : ILoggerProvider {
    public sealed record Entry(string Category, LogLevel Level, string Message, Exception? Exception);

    public ConcurrentQueue<Entry> Entries { get; } = new();

    public ILogger CreateLogger(string categoryName) => new Logger(categoryName, Entries);

    public void Dispose() {
    }

    private sealed class Logger(string category, ConcurrentQueue<Entry> entries) : ILogger {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(
            LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter) =>
            entries.Enqueue(new Entry(category, logLevel, formatter(state, exception), exception));
    }
}
