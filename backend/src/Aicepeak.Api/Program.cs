using Aicepeak.Api.Configuration;
using Aicepeak.Api.Data;
using Aicepeak.Api.Health;

var builder = WebApplication.CreateBuilder(args);

// Configuration comes from environment variables; in Development also from .env (lowest precedence).
builder.Configuration.AddDotEnvInDevelopment(builder.Environment);

builder.Services.AddDatabase(builder.Configuration);
builder.Services.AddHealth();
builder.Services.AddProblemDetails();
builder.Services.AddControllers();
builder.Services.AddOpenApi();
// Microsoft Entra ID (later): AddAuthentication().AddMicrosoftIdentityWebApi(...)
// and AddAuthorization with an authenticated-user fallback policy.

var app = builder.Build();

if (!app.Environment.IsDevelopment())
{
    // Problem details without exception details; Development uses the developer exception page.
    app.UseExceptionHandler();
    app.UseHsts();
    app.UseHttpsRedirection();
}

// The built frontend (wwwroot, copied on publish). Static files stay public.
app.UseStaticFiles();
app.UseRouting();
// app.UseAuthentication(); // Microsoft Entra ID (later)
app.UseAuthorization();

app.MapHealth();
app.MapControllers();

if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

// Unknown API routes are 404 and never fall through to the frontend.
app.Map("/api/{**path}", () => Results.NotFound());
app.MapFallbackToFile("index.html").AllowAnonymous();

app.Run();
