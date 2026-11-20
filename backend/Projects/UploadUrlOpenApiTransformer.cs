using Microsoft.AspNetCore.OpenApi;
using Microsoft.OpenApi;

namespace Aicepeak.Api.Projects;

/// <summary>
/// OpenAPI only: <c>POST /project/{id}/upload-url</c> answers 200 with either an upload URL or the duplicate
/// document. Endpoint metadata keeps one type per status code, so this makes that response a <c>oneOf</c> of the
/// <see cref="UploadUrlResponse"/> and <see cref="DuplicateDocumentResponse"/> component schemas.
/// </summary>
internal sealed class UploadUrlOpenApiTransformer : IOpenApiOperationTransformer {
    public async Task TransformAsync(OpenApiOperation operation, OpenApiOperationTransformerContext context, CancellationToken cancellationToken) {
        if (!context.Description.ActionDescriptor.EndpointMetadata.OfType<IEndpointNameMetadata>()
                .Any(name => name.EndpointName == ProjectEndpoints.UploadUrlEndpointName)
            || context.Document is not { } document) {
            return;
        }

        var schema = new OpenApiSchema {
            OneOf = [
                await ComponentAsync<UploadUrlResponse>(document, context, cancellationToken),
                await ComponentAsync<DuplicateDocumentResponse>(document, context, cancellationToken),
            ],
        };
        operation.Responses ??= [];
        operation.Responses[StatusCodes.Status200OK.ToString()] = new OpenApiResponse {
            Description = "An upload URL, or the tenant's document with the same content, name and size.",
            Content = new Dictionary<string, OpenApiMediaType> { ["application/json"] = new() { Schema = schema } },
        };
    }

    /// <summary>A reference to the component schema of <typeparamref name="T"/>, registered if the document lacks it.</summary>
    private static async Task<OpenApiSchemaReference> ComponentAsync<T>(
        OpenApiDocument document, OpenApiOperationTransformerContext context, CancellationToken cancellationToken) {
        var id = typeof(T).Name;
        document.AddComponent<IOpenApiSchema>(id, await context.GetOrCreateSchemaAsync(typeof(T), cancellationToken: cancellationToken));
        return new OpenApiSchemaReference(id, document);
    }
}
