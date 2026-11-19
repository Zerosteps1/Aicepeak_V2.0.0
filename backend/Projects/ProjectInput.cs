using System.Globalization;
using System.Text.Json;
using Aicepeak.Api.Data.Entities;

namespace Aicepeak.Api.Projects;

/// <summary>
/// The fields of a <c>POST /project</c> or <c>PATCH /project/{id}</c> body, read from the JSON so that a missing
/// property and <c>null</c> stay distinct: a field is <c>null</c> here when it was missing or invalid. Every failure
/// is added to the <see cref="ValidationErrors"/>; nothing stops at the first one.
/// </summary>
internal sealed class ProjectInput {
    public const string DateFormat = "yyyy-MM-dd";

    public string? Name { get; private set; }

    public DateOnly? StartDate { get; private set; }

    /// <summary>True if <c>endDate</c> was given, as a date or as <c>null</c> (clears it).</summary>
    public bool HasEndDate { get; private set; }

    public DateOnly? EndDate { get; private set; }

    public string? Description { get; private set; }

    /// <summary>The <c>documents</c> of a PATCH, valid entries only; <c>null</c> if not given.</summary>
    public IReadOnlyList<DocumentRefInput>? Documents { get; private set; }

    /// <summary>A POST body: <c>name</c> and <c>startDate</c> required; <c>id</c> and <c>documents</c> not allowed.</summary>
    public static ProjectInput ParseCreate(JsonElement body, ValidationErrors errors) {
        var input = Parse(body, projectId: null, errors);
        if (input.Name is null && !errors.Has("name")) {
            errors.Add("name", "is required");
        }

        if (input.StartDate is null && !errors.Has("startDate")) {
            errors.Add("startDate", "is required");
        }

        input.CheckDates(currentStart: null, currentEnd: null, errors);
        return input;
    }

    /// <summary>A PATCH body: any subset of the fields; an <c>id</c> must be the project's.</summary>
    public static ProjectInput ParseUpdate(JsonElement body, Guid projectId, ValidationErrors errors) =>
        Parse(body, projectId, errors);

    /// <summary>The end date must not be before the start date, taking unchanged values from the project.</summary>
    public void CheckDates(DateOnly? currentStart, DateOnly? currentEnd, ValidationErrors errors) {
        var start = StartDate ?? currentStart;
        var end = HasEndDate ? EndDate : currentEnd;
        if (start is not null && end < start && !errors.Has("startDate") && !errors.Has("endDate")) {
            errors.Add(HasEndDate ? "endDate" : "startDate", "endDate must not be before startDate");
        }
    }

    private static ProjectInput Parse(JsonElement body, Guid? projectId, ValidationErrors errors) {
        var input = new ProjectInput();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in body.EnumerateObject()) {
            if (!seen.Add(property.Name)) {
                errors.Add(property.Name, "is given more than once");
                continue;
            }

            var value = property.Value;
            switch (property.Name) {
                case "name":
                    input.Name = ReadName(value, errors);
                    break;
                case "startDate":
                    input.StartDate = ReadDate(value, "startDate", errors);
                    break;
                case "endDate":
                    input.HasEndDate = true;
                    input.EndDate = value.ValueKind == JsonValueKind.Null ? null : ReadDate(value, "endDate", errors);
                    break;
                case "description":
                    input.Description = ReadDescription(value, errors);
                    break;
                case "id" when projectId is null:
                    errors.Add("id", "must not be given; the server assigns it");
                    break;
                case "id":
                    if (value.ValueKind != JsonValueKind.String || !Guid.TryParse(value.GetString(), out var id) || id != projectId) {
                        errors.Add("id", "does not match the project");
                    }

                    break;
                case "documents" when projectId is null:
                    errors.Add("documents", "must not be given; documents are added with PATCH");
                    break;
                case "documents":
                    input.Documents = DocumentRefInput.ParseList(value, errors);
                    break;
                default:
                    errors.Add(property.Name, "is not a known property");
                    break;
            }
        }

        return input;
    }

    private static string? ReadName(JsonElement value, ValidationErrors errors) {
        if (value.ValueKind != JsonValueKind.String) {
            errors.Add("name", "must be a string");
            return null;
        }

        var name = value.GetString()!.Trim();
        if (name.Length == 0) {
            errors.Add("name", "must not be empty");
        } else if (name.Length > Project.MaxNameLength) {
            errors.Add("name", $"must be at most {Project.MaxNameLength} characters");
        } else if (name.Any(char.IsControl)) {
            errors.Add("name", "must not contain control characters");
        } else {
            return name;
        }

        return null;
    }

    private static DateOnly? ReadDate(JsonElement value, string field, ValidationErrors errors) {
        if (value.ValueKind == JsonValueKind.String
            && DateOnly.TryParseExact(value.GetString(), DateFormat, CultureInfo.InvariantCulture, DateTimeStyles.None, out var date)) {
            return date;
        }

        errors.Add(field, $"must be a date ({DateFormat})");
        return null;
    }

    private static string? ReadDescription(JsonElement value, ValidationErrors errors) {
        if (value.ValueKind != JsonValueKind.String) {
            errors.Add("description", "must be a string");
            return null;
        }

        var description = value.GetString()!;
        if (description.Length <= Project.MaxDescriptionLength) {
            return description;
        }

        errors.Add("description", $"must be at most {Project.MaxDescriptionLength} characters");
        return null;
    }
}

/// <summary>An entry of <c>documents</c> in a PATCH body: <c>{url, name, size, contentType}</c> at <see cref="Index"/>.</summary>
internal sealed record DocumentRefInput(int Index, Uri Url, string Name, long Size, string ContentType) {
    public string Field(string property) => $"documents[{Index}].{property}";

    /// <summary>The valid entries of a <c>documents</c> array; a failure for each invalid one.</summary>
    public static IReadOnlyList<DocumentRefInput>? ParseList(JsonElement value, ValidationErrors errors) {
        if (value.ValueKind != JsonValueKind.Array) {
            errors.Add("documents", "must be an array");
            return null;
        }

        var entries = new List<DocumentRefInput>();
        var index = 0;
        foreach (var item in value.EnumerateArray()) {
            if (Parse(item, index++, errors) is { } entry) {
                entries.Add(entry);
            }
        }

        return entries;
    }

    private static DocumentRefInput? Parse(JsonElement item, int index, ValidationErrors errors) {
        var prefix = $"documents[{index}]";
        if (item.ValueKind != JsonValueKind.Object) {
            errors.Add(prefix, "must be an object");
            return null;
        }

        Uri? url = null;
        string? name = null;
        string? contentType = null;
        long? size = null;
        var valid = true;
        foreach (var property in item.EnumerateObject()) {
            var field = $"{prefix}.{property.Name}";
            var value = property.Value;
            switch (property.Name) {
                case "url" when url is null:
                    url = ReadUrl(value, field, errors);
                    valid &= url is not null;
                    break;
                case "name" when name is null:
                    name = ReadString(value, field, errors);
                    valid &= name is not null;
                    break;
                case "contentType" when contentType is null:
                    contentType = ReadString(value, field, errors);
                    valid &= contentType is not null;
                    break;
                case "size" when size is null:
                    if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number)) {
                        size = number;
                    } else {
                        errors.Add(field, "must be an integer");
                        valid = false;
                    }

                    break;
                case "url" or "name" or "contentType" or "size":
                    errors.Add(field, "is given more than once");
                    valid = false;
                    break;
                default:
                    errors.Add(field, "is not a known property");
                    valid = false;
                    break;
            }
        }

        foreach (var (property, present) in new[] { ("url", url is not null), ("name", name is not null), ("size", size is not null), ("contentType", contentType is not null) }) {
            if (!present && !errors.Has($"{prefix}.{property}")) {
                errors.Add($"{prefix}.{property}", "is required");
                valid = false;
            }
        }

        return valid ? new DocumentRefInput(index, url!, name!, size!.Value, contentType!) : null;
    }

    /// <summary>An absolute http(s) URL without query or fragment: the signed query of an upload URL must be removed.</summary>
    private static Uri? ReadUrl(JsonElement value, string field, ValidationErrors errors) {
        if (ReadString(value, field, errors) is not { } text) {
            return null;
        }

        if (text.Contains('?') || text.Contains('#')) {
            errors.Add(field, "must not contain a query or fragment");
            return null;
        }

        if (Uri.TryCreate(text, UriKind.Absolute, out var url) && (url.Scheme == Uri.UriSchemeHttps || url.Scheme == Uri.UriSchemeHttp)) {
            return url;
        }

        errors.Add(field, "must be an absolute URL");
        return null;
    }

    private static string? ReadString(JsonElement value, string field, ValidationErrors errors) {
        if (value.ValueKind == JsonValueKind.String) {
            return value.GetString();
        }

        errors.Add(field, "must be a string");
        return null;
    }
}
