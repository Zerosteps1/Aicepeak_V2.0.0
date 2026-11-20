using System.Net.Http.Json;
using System.Text.Json;
using Aicepeak.Api.Projects;
using Aicepeak.Api.Tests.Infrastructure;

namespace Aicepeak.Api.Tests.Projects;

/// <summary>
/// The OpenAPI document of Development describes the project endpoints, without a database: the request bodies, every
/// response, and both answers of upload-url. The documented request properties are exactly those the parsers read and
/// require, so the documentation cannot drift from <see cref="ProjectInput"/> and <see cref="UploadUrlInput"/>.
/// </summary>
public sealed class ProjectOpenApiTests(ProjectOpenApiTests.OpenApiDocumentFixture openApi) : IClassFixture<ProjectOpenApiTests.OpenApiDocumentFixture> {
    private const string Project = "/api/v1/project";
    private const string ProjectById = Project + "/{id}";
    private const string UploadUrl = ProjectById + "/upload-url";
    private const string DeleteDocument = ProjectById + "/document/{documentId}";
    private const string Validation = ProjectById + "/document-validation/sse";
    private const string Extraction = ProjectById + "/document-extraction/sse";

    private const string Problem = "application/problem+json HttpValidationProblemDetails";
    private const string NoBody = "";

    /// <summary>The reasons of a property that the parser did not read.</summary>
    private static readonly string[] NotRead = ["is not a known property", "is required"];

    public static TheoryData<string, string, string[]> Responses => new() {
        { "post", Project, ["201 application/json ProjectResponse", $"400 {Problem}", $"415 {NoBody}"] },
        { "get", ProjectById, ["200 application/json ProjectResponse", $"404 {NoBody}"] },
        { "patch", ProjectById, ["200 application/json ProjectResponse", $"400 {Problem}", $"404 {NoBody}", $"415 {NoBody}"] },
        {
            "post", UploadUrl,
            ["200 application/json oneOf(UploadUrlResponse, DuplicateDocumentResponse)", $"400 {Problem}", $"404 {NoBody}", $"415 {NoBody}"]
        },
        { "delete", DeleteDocument, [$"204 {NoBody}", $"404 {NoBody}"] },
        { "get", Validation, ["200 text/event-stream DocumentProgressEvent", $"404 {NoBody}"] },
        { "get", Extraction, ["200 text/event-stream DocumentProgressEvent", $"404 {NoBody}"] },
    };

    [Theory]
    [InlineData("post", Project, "CreateProjectRequest")]
    [InlineData("patch", ProjectById, "UpdateProjectRequest")]
    [InlineData("post", UploadUrl, "UploadUrlRequest")]
    [InlineData("get", ProjectById, null)]
    [InlineData("delete", DeleteDocument, null)]
    [InlineData("get", Validation, null)]
    [InlineData("get", Extraction, null)]
    public void RequestBody_IsTheRequiredJsonDocumentationRecord(string method, string path, string? schema) {
        var operation = Operation(method, path);

        if (schema is null) {
            Assert.False(operation.TryGetProperty("requestBody", out _));
            return;
        }

        var body = operation.GetProperty("requestBody");
        Assert.True(body.GetProperty("required").GetBoolean());
        var content = Assert.Single(body.GetProperty("content").EnumerateObject());
        Assert.Equal("application/json", content.Name);
        Assert.Equal(schema, ReferencedSchema(content.Value.GetProperty("schema")));
    }

    [Theory]
    [MemberData(nameof(Responses))]
    public void Responses_AreDocumented(string method, string path, string[] expected) {
        var responses = Operation(method, path).GetProperty("responses").EnumerateObject()
            .Select(response => $"{response.Name} {Content(response.Value)}");

        Assert.Equal(expected, responses.Order(StringComparer.Ordinal));
    }

    [Fact]
    public void UploadUrl_200_IsOneOfTheTwoComponentSchemas() {
        var schema = Operation("post", UploadUrl).GetProperty("responses").GetProperty("200")
            .GetProperty("content").GetProperty("application/json").GetProperty("schema");

        Assert.Equal(
            ["UploadUrlResponse", "DuplicateDocumentResponse"],
            schema.GetProperty("oneOf").EnumerateArray().Select(ReferencedSchema));
        Assert.Equal(["blobUrl", "expires"], Properties(Component("UploadUrlResponse")));
        Assert.Equal(["document"], Properties(Component("DuplicateDocumentResponse")));
        Assert.Equal("DocumentRef", ReferencedSchema(Component("DuplicateDocumentResponse").GetProperty("properties").GetProperty("document")));
    }

    [Theory]
    [InlineData("CreateProjectRequest")]
    [InlineData("UpdateProjectRequest")]
    [InlineData("UploadUrlRequest")]
    [InlineData("DocumentRef")]
    public void DocumentedRequestProperties_AreThePropertiesTheParserAccepts_AndRequires(string schema) {
        var (accepted, required) = Parser(schema);
        var component = Component(schema);

        Assert.Equal(accepted.Order(StringComparer.Ordinal), Properties(component).Order(StringComparer.Ordinal));
        var documentedRequired = component.TryGetProperty("required", out var names) ? names.EnumerateArray().Select(name => name.GetString()!) : [];
        Assert.Equal(required.Order(StringComparer.Ordinal), documentedRequired.Order(StringComparer.Ordinal));
    }

    [Theory]
    [InlineData("UploadUrlRequest", "size")]
    [InlineData("DocumentRef", "documents[0].size")]
    public void Size_IsDocumentedAsAJsonInteger_AndTheParserRefusesItAsAString(string schema, string field) {
        var size = Component(schema).GetProperty("properties").GetProperty("size");

        Assert.Equal(["integer"], Types(size));
        Assert.Equal("int64", size.GetProperty("format").GetString());
        Assert.False(size.TryGetProperty("pattern", out _));
        var failures = schema == "DocumentRef" ? ParseUpdate("""{"documents":[{"size":"123"}]}""") : ParseUploadUrl("""{"size":"123"}""");
        Assert.StartsWith("must be an integer", Assert.Single(Failures(failures, field)));
    }

    [Fact]
    public void Numbers_AreNeverDocumentedAsStrings() {
        // The parsers read numbers only as JSON numbers, and responses write them as numbers.
        var numbersAlsoStrings = Objects(openApi.Root, "#")
            .Where(schema => Types(schema.Value) is var types && types.Contains("string") && (types.Contains("integer") || types.Contains("number")))
            .Select(schema => schema.Path);

        Assert.Empty(numbersAlsoStrings);
        Assert.Equal(["integer"], Types(Component("DocumentProgressEvent").GetProperty("properties").GetProperty("overallProgress")));
    }

    [Fact]
    public void EveryAcceptedProperty_IsRead_AndPostRefusesThePatchOnlyOnes() {
        // true is invalid for every property, so each one read fails with its own reason, never as unknown.
        foreach (var property in ProjectInput.UpdateProperties) {
            Assert.DoesNotContain(NotRead, Failures(ParseUpdate($$"""{"{{property}}":true}"""), property));
        }

        foreach (var property in ProjectInput.CreateProperties) {
            Assert.DoesNotContain(NotRead, Failures(ParseCreate($$"""{"{{property}}":true}"""), property));
        }

        foreach (var property in ProjectInput.UpdateProperties.Except(ProjectInput.CreateProperties)) {
            Assert.StartsWith("must not be given", Assert.Single(Failures(ParseCreate($$"""{"{{property}}":true}"""), property)));
        }

        foreach (var property in UploadUrlInput.Properties) {
            Assert.DoesNotContain(NotRead, Failures(ParseUploadUrl($$"""{"{{property}}":true}"""), property));
        }

        foreach (var property in DocumentRefInput.Properties) {
            Assert.DoesNotContain(NotRead, Failures(ParseUpdate($$"""{"documents":[{"{{property}}":true}]}"""), $"documents[0].{property}"));
        }

        Assert.Equal(["is not a known property"], Failures(ParseUpdate("""{"color":true}"""), "color"));
    }

    private JsonElement Operation(string method, string path) => openApi.Root.GetProperty("paths").GetProperty(path).GetProperty(method);

    private JsonElement Component(string schema) => openApi.Root.GetProperty("components").GetProperty("schemas").GetProperty(schema);

    private static IEnumerable<string> Properties(JsonElement schema) => schema.GetProperty("properties").EnumerateObject().Select(property => property.Name);

    /// <summary>The types of a schema, given as one name or as a list; empty without <c>type</c>.</summary>
    private static string[] Types(JsonElement schema) => !schema.TryGetProperty("type", out var type) ? [] : type.ValueKind switch {
        JsonValueKind.String => [type.GetString()!],
        JsonValueKind.Array => [.. type.EnumerateArray().Where(name => name.ValueKind == JsonValueKind.String).Select(name => name.GetString()!)],
        _ => [],
    };

    /// <summary>Every JSON object within <paramref name="element"/>, itself included, with its JSON pointer.</summary>
    private static IEnumerable<(string Path, JsonElement Value)> Objects(JsonElement element, string path) {
        IEnumerable<(string Path, JsonElement Value)> nested = element.ValueKind switch {
            JsonValueKind.Object => element.EnumerateObject().SelectMany(property => Objects(property.Value, $"{path}/{property.Name}")),
            JsonValueKind.Array => element.EnumerateArray().SelectMany((item, index) => Objects(item, $"{path}/{index}")),
            _ => [],
        };
        return element.ValueKind == JsonValueKind.Object ? nested.Prepend((path, element)) : nested;
    }

    /// <summary>The component name of a <c>$ref</c> schema, e.g. <c>ProjectResponse</c>.</summary>
    private static string ReferencedSchema(JsonElement schema) =>
        schema.GetProperty("$ref").GetString()!.Split('/') is ["#", "components", "schemas", var name] ? name : throw new FormatException(schema.ToString());

    /// <summary>A response's media type and schema, e.g. <c>application/json ProjectResponse</c>; empty without a body.</summary>
    private static string Content(JsonElement response) {
        if (!response.TryGetProperty("content", out var content)) {
            return NoBody;
        }

        var media = Assert.Single(content.EnumerateObject());
        var schema = media.Value.GetProperty("schema");
        var described = schema.TryGetProperty("oneOf", out var options)
            ? $"oneOf({string.Join(", ", options.EnumerateArray().Select(ReferencedSchema))})"
            : ReferencedSchema(schema);
        return $"{media.Name} {described}";
    }

    /// <summary>The properties a parser accepts for a documented schema, and those it requires (failing <c>{}</c>).</summary>
    private static (IEnumerable<string> Accepted, IEnumerable<string> Required) Parser(string schema) => schema switch {
        "CreateProjectRequest" => (ProjectInput.CreateProperties, RequiredFields(ParseCreate("{}"), "")),
        "UpdateProjectRequest" => (ProjectInput.UpdateProperties, RequiredFields(ParseUpdate("{}"), "")),
        "UploadUrlRequest" => (UploadUrlInput.Properties, RequiredFields(ParseUploadUrl("{}"), "")),
        "DocumentRef" => (DocumentRefInput.Properties, RequiredFields(ParseUpdate("""{"documents":[{}]}"""), "documents[0].")),
        _ => throw new ArgumentOutOfRangeException(nameof(schema)),
    };

    private static IEnumerable<string> RequiredFields(Dictionary<string, string[]> failures, string prefix) =>
        failures.Where(failure => failure.Value.Contains("is required")).Select(failure => failure.Key[prefix.Length..]);

    private static string[] Failures(Dictionary<string, string[]> failures, string field) {
        Assert.True(failures.TryGetValue(field, out var reasons), $"{field} has no failure, so it was not read.");
        return reasons;
    }

    private static Dictionary<string, string[]> ParseCreate(string json) => Parse(json, (body, errors) => ProjectInput.ParseCreate(body, errors));

    private static Dictionary<string, string[]> ParseUpdate(string json) => Parse(json, (body, errors) => ProjectInput.ParseUpdate(body, Guid.Empty, errors));

    private static Dictionary<string, string[]> ParseUploadUrl(string json) => Parse(json, (body, errors) => UploadUrlInput.Parse(body, errors));

    private static Dictionary<string, string[]> Parse(string json, Action<JsonElement, ValidationErrors> parse) {
        var errors = new ValidationErrors();
        using var body = JsonDocument.Parse(json);
        parse(body.RootElement, errors);
        return errors.Any ? errors.ToProblem().ProblemDetails.Errors.ToDictionary() : new();
    }

    /// <summary><c>/openapi/v1.json</c> of the API in Development, fetched once for all tests of the class.</summary>
    public sealed class OpenApiDocumentFixture : IAsyncLifetime {
        public JsonElement Root { get; private set; }

        public async ValueTask InitializeAsync() {
            await using var factory = new ApiFactory(TestSettings.Development, TestSettings.WithEntra(TestSettings.UnreachableDatabase()));
            using var response = await factory.CreateClient().GetAsync("/openapi/v1.json", TestContext.Current.CancellationToken);
            response.EnsureSuccessStatusCode();
            Root = await response.Content.ReadFromJsonAsync<JsonElement>(TestContext.Current.CancellationToken);
        }

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
}
