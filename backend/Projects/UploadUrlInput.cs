using System.Collections.Frozen;
using System.Text.Json;

namespace Aicepeak.Api.Projects;

/// <summary>
/// The body of <c>POST /project/{id}/upload-url</c>: <c>{sha256, name, size, contentType}</c>. The browser's hash only
/// serves the duplicate lookup; the stored hash is computed by the backend.
/// </summary>
internal sealed record UploadUrlInput(byte[] Sha256, string Name, long Size, string ContentType) {
    /// <summary>The properties of the body, documented by <see cref="UploadUrlRequest"/>; any other is unknown.</summary>
    public static readonly FrozenSet<string> Properties = ["sha256", "name", "size", "contentType"];

    public static UploadUrlInput? Parse(JsonElement body, ValidationErrors errors) {
        byte[]? sha256 = null;
        string? name = null;
        string? contentType = null;
        long? size = null;
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in body.EnumerateObject()) {
            var value = property.Value;
            if (!seen.Add(property.Name)) {
                errors.Add(property.Name, "is given more than once");
                continue;
            }

            if (!Properties.Contains(property.Name)) {
                errors.Add(property.Name, "is not a known property");
                continue;
            }

            switch (property.Name) {
                case "sha256":
                    sha256 = ReadSha256(value, errors);
                    break;
                case "name":
                    if (value.ValueKind == JsonValueKind.String && DocumentRules.IsValidName(value.GetString()!)) {
                        name = value.GetString();
                    } else {
                        errors.Add("name", DocumentRules.NameRule);
                    }

                    break;
                case "size":
                    if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number) && DocumentRules.IsValidSize(number)) {
                        size = number;
                    } else {
                        errors.Add("size", DocumentRules.SizeRule);
                    }

                    break;
                case "contentType":
                    if (value.ValueKind == JsonValueKind.String && DocumentRules.IsValidContentType(value.GetString()!)) {
                        contentType = value.GetString();
                    } else {
                        errors.Add("contentType", DocumentRules.ContentTypeRule);
                    }

                    break;
            }
        }

        foreach (var (field, present) in new[] { ("sha256", sha256 is not null), ("name", name is not null), ("size", size is not null), ("contentType", contentType is not null) }) {
            if (!present && !errors.Has(field)) {
                errors.Add(field, "is required");
            }
        }

        return errors.Any ? null : new UploadUrlInput(sha256!, name!, size!.Value, contentType!);
    }

    private static byte[]? ReadSha256(JsonElement value, ValidationErrors errors) {
        var text = value.ValueKind == JsonValueKind.String ? value.GetString()! : "";
        if (text.Length == 64 && text.All(char.IsAsciiHexDigit)) {
            return Convert.FromHexString(text);
        }

        errors.Add("sha256", "must be a SHA-256 hash of 64 hex digits");
        return null;
    }
}
