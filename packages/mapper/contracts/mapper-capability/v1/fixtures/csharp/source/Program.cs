using System;

public class Service
{
    public int Compute(int value) => value;
    public string Compute(string value) => value;

    public void Run()
    {
        Compute(1);
        Compute("x");
    }
}
