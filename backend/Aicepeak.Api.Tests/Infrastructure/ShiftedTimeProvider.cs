namespace Aicepeak.Api.Tests.Infrastructure;

/// <summary>The system clock moved by <see cref="Offset"/>, e.g. to sign an upload URL in the past.</summary>
public sealed class ShiftedTimeProvider(TimeSpan offset) : TimeProvider {
    public TimeSpan Offset { get; set; } = offset;

    public override DateTimeOffset GetUtcNow() => TimeProvider.System.GetUtcNow() + Offset;
}
