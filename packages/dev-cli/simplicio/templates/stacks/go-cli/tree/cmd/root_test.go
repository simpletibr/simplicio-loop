package cmd

import (
	"bytes"
	"testing"
)

func TestRootCommand(t *testing.T) {
	var out bytes.Buffer
	rootCmd.SetOut(&out)
	rootCmd.SetArgs([]string{"--name", "Simplicio"})

	if err := rootCmd.Execute(); err != nil {
		t.Fatal(err)
	}
	if out.String() != "hello Simplicio\n" {
		t.Fatalf("unexpected output: %q", out.String())
	}
}
