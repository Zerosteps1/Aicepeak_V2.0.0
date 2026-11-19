using System.Reflection;
using System.Reflection.Emit;
using Aicepeak.Api.Data;
using Aicepeak.Api.Data.Entities;
using Aicepeak.Api.Documents.Analysis;
using Aicepeak.Api.Storage.Azure;

namespace Aicepeak.Api.Tests.Architecture;

/// <summary>
/// Boundaries checked by reflection over the API assembly, including compiler-generated types (lambdas, async state
/// machines) and the members every method body uses (read from its IL):
/// the document analysis (AC-22) knows documents but nothing of projects, and only the Azure adapter uses the Azure SDK.
/// </summary>
public sealed class ArchitectureTests {
    private static readonly Assembly Api = typeof(Program).Assembly;

    [Fact]
    public void AC22_DocumentAnalysis_AndDocument_DoNotReferenceProjects() {
        var analysis = Api.GetTypes()
            .Where(type => IsIn(type, "Aicepeak.Api.Documents.Analysis") || type == typeof(Document) || type.DeclaringType == typeof(Document))
            .ToList();
        Assert.Contains(typeof(DocumentAnalyzer), analysis);

        var violations = analysis
            .SelectMany(type => References(type).Select(reference => (type, reference)))
            .Where(pair => IsIn(pair.reference, "Aicepeak.Api.Projects")
                || pair.reference == typeof(Project)
                || pair.reference == typeof(ProjectDocument)
                || pair.reference == typeof(TenantDbContext))
            .Select(pair => $"{pair.type.FullName} -> {pair.reference.FullName}")
            .Distinct();

        Assert.Empty(violations);
        // The scan sees what the analysis does use.
        Assert.Contains(typeof(Document), References(typeof(DocumentAnalyzer)));
    }

    [Fact]
    public void OnlyTheAzureAdapter_ReferencesTheAzureSdk() {
        var violations = Api.GetTypes()
            .Where(type => !IsIn(type, "Aicepeak.Api.Storage.Azure"))
            .SelectMany(type => References(type).Select(reference => (type, reference)))
            .Where(pair => IsIn(pair.reference, "Azure"))
            .Select(pair => $"{pair.type.FullName} -> {pair.reference.FullName}")
            .Distinct();

        Assert.Empty(violations);
        // The scan sees the SDK where it is used, also inside the adapter's lambdas and state machines.
        var adapter = Api.GetTypes().Where(type => IsIn(type, "Aicepeak.Api.Storage.Azure")).SelectMany(References).ToHashSet();
        Assert.Contains(adapter, type => type.FullName == "Azure.Storage.Blobs.BlobServiceClient");
        Assert.Contains(adapter, type => type.FullName == "Azure.Storage.Sas.BlobSasBuilder");
        Assert.Contains(adapter, type => type.FullName == "Azure.RequestFailedException");
    }

    private static bool IsIn(Type type, string ns) =>
        type.Namespace is { } name && (name == ns || name.StartsWith(ns + ".", StringComparison.Ordinal));

    /// <summary>Every type a type's declaration and method bodies mention, with generic arguments and element types.</summary>
    private static IEnumerable<Type> References(Type type) => Direct(type).SelectMany(Expand).Distinct();

    private static IEnumerable<Type> Direct(Type type) {
        const BindingFlags all = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
        if (type.BaseType is { } baseType) {
            yield return baseType;
        }

        foreach (var item in type.GetInterfaces()
                     .Concat(type.GetCustomAttributesData().Select(attribute => attribute.AttributeType))
                     .Concat(type.GetFields(all).Select(field => field.FieldType))
                     .Concat(type.GetProperties(all).Select(property => property.PropertyType))
                     .Concat(type.GetEvents(all).Select(@event => @event.EventHandlerType!))) {
            yield return item;
        }

        foreach (var method in type.GetMethods(all).Cast<MethodBase>().Concat(type.GetConstructors(all))) {
            foreach (var item in Signature(method)) {
                yield return item;
            }

            if (method.GetMethodBody() is not { } body) {
                continue;
            }

            foreach (var local in body.LocalVariables) {
                yield return local.LocalType;
            }

            foreach (var member in UsedMembers(method, body.GetILAsByteArray()!)) {
                foreach (var item in member switch {
                    Type used => [used],
                    FieldInfo field => [field.DeclaringType!, field.FieldType],
                    MethodBase called => Signature(called).Append(called.DeclaringType!),
                    _ => [],
                }) {
                    yield return item;
                }
            }
        }
    }

    private static IEnumerable<Type> Signature(MethodBase method) {
        var types = method.GetParameters().Select(parameter => parameter.ParameterType);
        if (method is MethodInfo info) {
            types = types.Append(info.ReturnType);
            if (info.IsGenericMethod) {
                types = types.Concat(info.GetGenericArguments());
            }
        }

        return types;
    }

    private static IEnumerable<Type> Expand(Type type) {
        yield return type;
        if (type.HasElementType) {
            foreach (var item in Expand(type.GetElementType()!)) {
                yield return item;
            }
        }

        if (type.IsGenericType && !type.IsGenericTypeDefinition) {
            foreach (var item in type.GetGenericArguments().SelectMany(Expand).Prepend(type.GetGenericTypeDefinition())) {
                yield return item;
            }
        }
    }

    private static readonly OpCode[] OneByteOpCodes = new OpCode[256];
    private static readonly OpCode[] TwoByteOpCodes = new OpCode[256];

    static ArchitectureTests() {
        foreach (var field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)) {
            var opCode = (OpCode)field.GetValue(null)!;
            var value = (ushort)opCode.Value;
            if (value >> 8 == 0xFE) {
                TwoByteOpCodes[value & 0xFF] = opCode;
            } else {
                OneByteOpCodes[value] = opCode;
            }
        }
    }

    /// <summary>The fields, methods and types an IL body refers to by metadata token.</summary>
    private static IEnumerable<MemberInfo> UsedMembers(MethodBase method, byte[] il) {
        var typeArguments = method.DeclaringType is { IsGenericType: true } declaring ? declaring.GetGenericArguments() : null;
        var methodArguments = method is MethodInfo { IsGenericMethod: true } generic ? generic.GetGenericArguments() : null;
        var position = 0;
        while (position < il.Length) {
            var opCode = il[position] == 0xFE ? TwoByteOpCodes[il[position + 1]] : OneByteOpCodes[il[position]];
            position += opCode.Size;
            switch (opCode.OperandType) {
                case OperandType.InlineField or OperandType.InlineMethod or OperandType.InlineTok or OperandType.InlineType:
                    yield return method.Module.ResolveMember(BitConverter.ToInt32(il, position), typeArguments, methodArguments)!;
                    position += 4;
                    break;
                case OperandType.InlineSwitch:
                    position += 4 + 4 * BitConverter.ToInt32(il, position);
                    break;
                case OperandType.InlineI8 or OperandType.InlineR:
                    position += 8;
                    break;
                case OperandType.InlineBrTarget or OperandType.InlineI or OperandType.InlineSig or OperandType.InlineString
                    or OperandType.ShortInlineR:
                    position += 4;
                    break;
                case OperandType.InlineVar:
                    position += 2;
                    break;
                case OperandType.ShortInlineBrTarget or OperandType.ShortInlineI or OperandType.ShortInlineVar:
                    position += 1;
                    break;
            }
        }
    }
}
