using System;

namespace Golden.Billing;

public sealed record Account(string Id);

public sealed class Service
{
    public Account Resolve(string value) => new(value);

    public Account Resolve(int value) => Resolve(value.ToString());
}

public static class ServiceTests
{
    public static void ResolvesAccount()
    {
        var account = new Service().Resolve(1);
        if (account.Id != "1") throw new InvalidOperationException();
    }
}
