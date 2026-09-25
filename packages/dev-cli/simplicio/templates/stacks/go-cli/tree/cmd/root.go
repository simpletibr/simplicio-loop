package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

var name string

var rootCmd = &cobra.Command{
	Use:   "{project_name}",
	Short: "{goal}",
	RunE: func(cmd *cobra.Command, args []string) error {
		_, err := fmt.Fprintf(cmd.OutOrStdout(), "hello %s\n", name)
		return err
	},
}

func init() {
	rootCmd.Flags().StringVar(&name, "name", "world", "name to greet")
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
