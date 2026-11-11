using Aicepeak.Api.Configuration;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace Aicepeak.Api.Data;

public static class DataServiceCollectionExtensions
{
    public static IServiceCollection AddDatabase(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<DatabaseOptions>().Bind(configuration);

        services.AddDbContext<AppDbContext>((serviceProvider, options) =>
        {
            var database = DatabaseConnectionString.Create(serviceProvider.GetRequiredService<IOptions<DatabaseOptions>>().Value);

            // Without valid settings the app still starts; the health endpoint reports the configuration as failing.
            if (database.IsValid)
            {
                options.UseNpgsql(database.ConnectionString);
            }
            else
            {
                options.UseNpgsql();
            }
        });

        return services;
    }
}
