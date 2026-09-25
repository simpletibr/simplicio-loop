var builder = WebApplication.CreateBuilder(args);
builder.Services.AddRazorComponents();

var app = builder.Build();
app.MapRazorComponents<App.Web.Components.App>();
app.MapGet("/health", () => Results.Ok(new { ok = true }));
app.Run();

namespace App.Web
{
    public partial class Program;
}
