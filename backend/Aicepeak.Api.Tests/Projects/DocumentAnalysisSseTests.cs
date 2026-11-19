using System.Net;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Documents.Analysis.Mock;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.Projects;

/// <summary>
/// The two SSE endpoints against a real PostgreSQL (Docker): they stream the mock analysis of exactly the documents
/// linked to the project; the last event has <c>overallProgress</c> 100.
/// </summary>
[Collection(PostgresCollection.Name)]
[Trait("Category", "Database")]
public sealed class DocumentAnalysisSseTests(PostgresFixture postgres) {
    private const string Base = TenantApi.Base;

    [Fact]
    public async Task Validation_StreamsTheLinkedDocuments_AndFlagsInvalidOnes() {
        await using var api = await TenantApi.CreateAsync(postgres);
        var projectId = await api.CreateProjectAsync();
        var otherProject = await api.CreateProjectAsync();
        var valid = await SeedAsync(api, projectId, "Bilanz 2025.pdf");
        var invalid = await SeedAsync(api, projectId, "invalid-scan.pdf");
        await SeedAsync(api, otherProject, "Andere.pdf");

        var response = await api.Client.GetAsync($"{Base}/{projectId}/document-validation/sse", TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var events = await ServerSentEvents.ReadAsync(response);
        Assert.Equal(10, events.Count);
        Assert.Equal([valid.Id.ToString(), invalid.Id.ToString()], events.Select(item => item.String("document")).Distinct());
        Assert.Equal([0, 12, 25, 37, 50, 50, 62, 75, 87, 100], events.Select(item => item.Int("overallProgress")!.Value));
        Assert.Equal(MockDocumentValidator.InvalidError, events[^1].String("error"));
        Assert.All(events[..^1], item => Assert.False(item.TryGetProperty("error", out _)));
        Assert.All(events, item => Assert.False(item.TryGetProperty("pages", out _)));
    }

    [Fact]
    public async Task Extraction_StreamsPagesAndPositions_UntilOverallProgress100() {
        await using var api = await TenantApi.CreateAsync(postgres);
        var projectId = await api.CreateProjectAsync();
        var document = await SeedAsync(api, projectId, "Bilanz 2025.pdf");

        var response = await api.Client.GetAsync($"{Base}/{projectId}/document-extraction/sse", TestContext.Current.CancellationToken);

        var events = await ServerSentEvents.ReadAsync(response);
        var pages = MockDocumentExtractor.PageCount(document);
        Assert.Equal(pages + 1, events.Count);
        Assert.Equal(Enumerable.Range(0, pages + 1), events.Select(item => item.Int("pagesRead")!.Value));
        Assert.Equal(pages * MockDocumentExtractor.PositionsPerPage, events[^1].Int("positions"));
        Assert.Equal(100, events[^1].Int("overallProgress"));
        Assert.Equal(pages, Assert.Single(events, item => item.Int("overallProgress") == 100).Int("pagesRead"));
        var position = events[^1].GetProperty("position");
        Assert.Equal(["name", "value", "period", "source", "page"], position.EnumerateObject().Select(property => property.Name));
        Assert.Equal(pages, position.GetProperty("page").GetInt32());
    }

    [Theory]
    [InlineData("document-validation")]
    [InlineData("document-extraction")]
    public async Task ProjectWithoutDocuments_StreamsOneFinalEvent(string stream) {
        await using var api = await TenantApi.CreateAsync(postgres);
        var projectId = await api.CreateProjectAsync();

        var response = await api.Client.GetAsync($"{Base}/{projectId}/{stream}/sse", TestContext.Current.CancellationToken);

        Assert.Equal(
            "data: {\"overallProgress\":100,\"document\":\"\"}\n\n",
            await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
    }

    [Theory]
    [InlineData("document-validation")]
    [InlineData("document-extraction")]
    public async Task UnknownProject_Returns404(string stream) {
        await using var api = await TenantApi.CreateAsync(postgres);
        await api.CreateProjectAsync();

        var response = await api.Client.GetAsync($"{Base}/{Guid.NewGuid()}/{stream}/sse", TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    /// <summary>A document row linked to the project; the stream never reads the file, so no blob is needed.</summary>
    private static async Task<Document> SeedAsync(TenantApi api, Guid projectId, string name) {
        var id = Guid.CreateVersion7();
        var document = new Document {
            Id = id,
            ProjectId = projectId,
            BlobName = $"{projectId}/{id}",
            Name = name,
            Size = 1000,
            ContentType = "application/pdf",
            Sha256 = new byte[32],
            CreatedAt = DateTimeOffset.UtcNow,
        };
        await using var db = api.CreateDb();
        db.AddRange(document, new ProjectDocument { ProjectId = projectId, DocumentId = id });
        await db.SaveChangesAsync(TestContext.Current.CancellationToken);
        return document;
    }
}
