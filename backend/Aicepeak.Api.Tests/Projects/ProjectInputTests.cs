using System.Text.Json;
using Aicepeak.Api.Projects;

namespace Aicepeak.Api.Tests.Projects;

/// <summary>
/// AC-5: POST and PATCH bodies are read as JSON documents, so a missing property and <c>null</c> stay distinct, and
/// every failure is collected with a short reason per field, without echoing input values.
/// </summary>
public sealed class ProjectInputTests {
    private static readonly Guid ProjectId = new("01930000-0000-7000-8000-000000000001");

    [Fact]
    public void AC05_Create_ValidBody_ReadsAllFields() {
        var (input, errors) = Create("""{"name":"  Forecast 2026 ","startDate":"2026-01-01","endDate":"2026-12-31","description":"Plan"}""");

        Assert.False(errors.Any);
        Assert.Equal("Forecast 2026", input.Name);
        Assert.Equal(new DateOnly(2026, 1, 1), input.StartDate);
        Assert.Equal(new DateOnly(2026, 12, 31), input.EndDate);
        Assert.Equal("Plan", input.Description);
    }

    [Fact]
    public void AC05_Create_OptionalFieldsMissing_IsValid() {
        var (input, errors) = Create("""{"name":"A","startDate":"2026-01-01"}""");

        Assert.False(errors.Any);
        Assert.False(input.HasEndDate);
        Assert.Null(input.Description);
    }

    [Fact]
    public void AC05_Create_ListsEveryFailure_OncePerField() {
        var (_, errors) = Create("""
            {"id":"x","documents":[],"startDate":"01.01.2026","endDate":"2026-13-01","description":7,"extra":true,"name":" "}
            """);

        Assert.Equal(
            new Dictionary<string, string[]> {
                ["id"] = ["must not be given; the server assigns it"],
                ["documents"] = ["must not be given; documents are added with PATCH"],
                ["startDate"] = ["must be a date (yyyy-MM-dd)"],
                ["endDate"] = ["must be a date (yyyy-MM-dd)"],
                ["description"] = ["must be a string"],
                ["extra"] = ["is not a known property"],
                ["name"] = ["must not be empty"],
            },
            Errors(errors));
    }

    [Fact]
    public void AC05_Create_RequiresNameAndStartDate() {
        var (_, errors) = Create("{}");

        Assert.Equal(new Dictionary<string, string[]> { ["name"] = ["is required"], ["startDate"] = ["is required"] }, Errors(errors));
    }

    [Theory]
    [InlineData("""{"name":null,"startDate":"2026-01-01"}""", "name", "must be a string")]
    [InlineData("""{"name":"A","startDate":null}""", "startDate", "must be a date (yyyy-MM-dd)")]
    [InlineData("""{"name":"A","startDate":"2026-01-01","description":null}""", "description", "must be a string")]
    [InlineData("""{"name":"A\nB","startDate":"2026-01-01"}""", "name", "must not contain control characters")]
    [InlineData("""{"name":"A","startDate":"2026-02-30"}""", "startDate", "must be a date (yyyy-MM-dd)")]
    [InlineData("""{"name":"A","startDate":"2026-01-01","endDate":"2025-12-31"}""", "endDate", "endDate must not be before startDate")]
    [InlineData("""{"Name":"A","name":"A","startDate":"2026-01-01"}""", "Name", "is not a known property")]
    [InlineData("""{"name":"A","name":"B","startDate":"2026-01-01"}""", "name", "is given more than once")]
    public void AC05_Create_InvalidField_FailsWithReason(string json, string field, string reason) {
        var (_, errors) = Create(json);

        Assert.Equal(new Dictionary<string, string[]> { [field] = [reason] }, Errors(errors));
    }

    [Fact]
    public void AC05_Create_TooLongValues_FailWithoutEchoingThem() {
        var (_, errors) = Create(JsonSerializer.Serialize(new {
            name = new string('n', 201),
            startDate = "2026-01-01",
            description = new string('d', 4001),
        }));

        Assert.Equal(
            new Dictionary<string, string[]> {
                ["name"] = ["must be at most 200 characters"],
                ["description"] = ["must be at most 4000 characters"],
            },
            Errors(errors));
    }

    [Fact]
    public void AC05_Create_LongestValues_AreValid() {
        var (_, errors) = Create(JsonSerializer.Serialize(new {
            name = new string('n', 200),
            startDate = "2026-01-01",
            endDate = "2026-01-01",
            description = new string('d', 4000),
        }));

        Assert.False(errors.Any);
    }

    [Fact]
    public void AC05_Update_MissingFieldsStayUnchanged_NullEndDateClears() {
        var (missing, _) = Update("{}");
        var (cleared, errors) = Update("""{"endDate":null}""");

        Assert.False(errors.Any);
        Assert.False(missing.HasEndDate);
        Assert.Null(missing.Name);
        Assert.Null(missing.Documents);
        Assert.True(cleared.HasEndDate);
        Assert.Null(cleared.EndDate);
    }

    [Theory]
    [InlineData("""{"id":"01930000-0000-7000-8000-000000000001"}""", true)]
    [InlineData("""{"id":"01930000-0000-7000-8000-000000000002"}""", false)]
    [InlineData("""{"id":null}""", false)]
    [InlineData("""{"id":"not-a-guid"}""", false)]
    public void AC05_Update_Id_MustBeTheProjects(string json, bool valid) {
        var (_, errors) = Update(json);

        var expected = valid ? new Dictionary<string, string[]>() : new() { ["id"] = ["does not match the project"] };
        Assert.Equal(expected, Errors(errors));
    }

    [Theory]
    [InlineData("2026-06-01", null, "2026-01-01", "startDate")]
    [InlineData(null, "2025-12-31", "2026-01-01", "endDate")]
    [InlineData("2026-02-01", "2026-01-31", null, "endDate")]
    public void AC05_Update_EndBeforeStart_ComparesWithTheStoredDates(string? start, string? end, string? storedStart, string field) {
        var body = new Dictionary<string, string?>();
        if (start is not null) {
            body["startDate"] = start;
        }

        if (end is not null) {
            body["endDate"] = end;
        }

        var (input, errors) = Update(JsonSerializer.Serialize(body));
        input.CheckDates(storedStart is null ? new DateOnly(2026, 1, 1) : DateOnly.Parse(storedStart), new DateOnly(2026, 5, 31), errors);

        Assert.Equal(new Dictionary<string, string[]> { [field] = ["endDate must not be before startDate"] }, Errors(errors));
    }

    [Fact]
    public void AC05_Update_Documents_AreReadAsReferences() {
        var (input, errors) = Update("""
            {"documents":[{"url":"https://storage.test/t/p/d","name":"a.pdf","size":12,"contentType":"application/pdf"}]}
            """);

        Assert.False(errors.Any);
        var entry = Assert.Single(input.Documents!);
        Assert.Equal((0, "https://storage.test/t/p/d", "a.pdf", 12L, "application/pdf"),
            (entry.Index, entry.Url.AbsoluteUri, entry.Name, entry.Size, entry.ContentType));
    }

    [Fact]
    public void AC05_Update_InvalidDocumentReferences_ListEveryFailureByIndex() {
        var (input, errors) = Update("""
            {"documents":[
              {"url":"https://storage.test/t/p/d","name":"a.pdf","size":1,"contentType":"application/pdf"},
              {"url":"https://storage.test/t/p/d?sv=1&sig=secret","name":"a.pdf","size":1.5,"contentType":"application/pdf"},
              "x",
              {"url":"relative/path","name":3,"extra":1},
              {"url":"https://storage.test/t/p/d#f","name":"a.pdf","size":"1","contentType":null}
            ]}
            """);

        Assert.Single(input.Documents!);
        var failures = Errors(errors);
        Assert.Equal(
            new Dictionary<string, string[]> {
                ["documents[1].url"] = ["must not contain a query or fragment"],
                ["documents[1].size"] = ["must be an integer"],
                ["documents[2]"] = ["must be an object"],
                ["documents[3].url"] = ["must be an absolute URL"],
                ["documents[3].name"] = ["must be a string"],
                ["documents[3].extra"] = ["is not a known property"],
                ["documents[3].size"] = ["is required"],
                ["documents[3].contentType"] = ["is required"],
                ["documents[4].url"] = ["must not contain a query or fragment"],
                ["documents[4].size"] = ["must be an integer"],
                ["documents[4].contentType"] = ["must be a string"],
            },
            failures);
        Assert.DoesNotContain("secret", JsonSerializer.Serialize(failures));
    }

    [Fact]
    public void AC05_Update_DocumentsNotAnArray_Fails() {
        var (_, errors) = Update("""{"documents":{}}""");

        Assert.Equal(new Dictionary<string, string[]> { ["documents"] = ["must be an array"] }, Errors(errors));
    }

    private static (ProjectInput Input, ValidationErrors Errors) Create(string json) {
        var errors = new ValidationErrors();
        using var body = JsonDocument.Parse(json);
        return (ProjectInput.ParseCreate(body.RootElement, errors), errors);
    }

    private static (ProjectInput Input, ValidationErrors Errors) Update(string json) {
        var errors = new ValidationErrors();
        using var body = JsonDocument.Parse(json);
        return (ProjectInput.ParseUpdate(body.RootElement, ProjectId, errors), errors);
    }

    private static Dictionary<string, string[]> Errors(ValidationErrors errors) =>
        errors.Any ? errors.ToProblem().ProblemDetails.Errors.ToDictionary() : new Dictionary<string, string[]>();
}
