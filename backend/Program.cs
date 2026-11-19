using Aicepeak.Api.Auth;
using Aicepeak.Api.Configuration;
using Aicepeak.Api.Data;
using Aicepeak.Api.Documents.Analysis;
using Aicepeak.Api.Frontend;
using Aicepeak.Api.Health;
using Aicepeak.Api.Projects;
using Aicepeak.Api.Storage;

var builder = WebApplication.CreateBuilder(args);

// Configuration comes from environment variables; in Development also from .env (lowest precedence).
builder.Configuration.AddDotEnvInDevelopment(builder.Environment);

builder.Services.AddDatabase(builder.Configuration);
builder.Services.AddBlobStorage(builder.Configuration);
builder.Services.AddDocumentAnalysis(builder.Configuration);
builder.Services.AddEntraAuthentication(builder.Configuration);
builder.Services.AddHealth();
builder.Services.AddProblemDetails();
builder.Services.AddControllers();
builder.Services.AddOpenApi();

var app = builder.Build();

if (!app.Environment.IsDevelopment()) {
    // Problem details without exception details; Development uses the developer exception page.
    app.UseExceptionHandler();
    app.UseHsts();
    app.UseHttpsRedirection();
}

// The built frontend (wwwroot, copied on publish). Static files stay public.
app.UseFrontendStaticFiles();
app.UseRouting();
app.UseAuthentication();
app.UseAuthorization();

// Health, the OpenAPI document (Development) and the frontend fallback are anonymous; API endpoints require a token.
app.MapHealth();
app.MapGroup("/api/v1").RequireAuthorization().MapLogin().MapProjects();
app.MapControllers().RequireAuthorization();

if (app.Environment.IsDevelopment()) {
    app.MapOpenApi();
}

app.MapFrontendFallback();

app.Run();
