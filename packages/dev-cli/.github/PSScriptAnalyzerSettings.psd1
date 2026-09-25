# PSScriptAnalyzer settings for LLM Project Mapper.
#
# Used by:
#   - .github/workflows/scaffold-self-check.yml (psanalyze job)
#   - scripts/lint.js (local `npm run lint`)
#
# Rationale for each excluded rule:
#
# PSUseApprovedVerbs — bootstrap.ps1 is a SCRIPT, not a module. Its private
# helpers (`Detect-Stack`, `Has-Cmd`, `Require-Cmd`, etc.) are not exported
# cmdlets, so the approved-verb constraint adds churn without auto-discovery
# benefit. Renaming them all would touch ~200 call sites.
#
# PSAvoidUsingInvokeExpression — `scripts/test.ps1` is a stack-neutral
# template runner that deliberately invokes a user-configured TEST_COMMAND.
# The alternative (`& $cmd`) breaks when the command contains pipes/redirects.
# Inputs originate from a developer-controlled env var, not user input.
#
# PSAvoidUsingEmptyCatchBlock — `.claude/hooks/post-edit.ps1` and
# `.codex/hooks/*.ps1` swallow prettier/eslint failures on purpose: the hook
# is best-effort formatting; the hard gate lives in pre-commit.
#
# PSAvoidUsingWriteHost — bootstrap.ps1 talks to a TTY; Write-Host is the
# correct choice for interactive prompts.
#
# PSUseShouldProcessForStateChangingFunctions — bootstrap.ps1 helpers don't
# pretend to be cmdlets; -WhatIf/-Confirm semantics don't apply.

@{
  # Block only on Errors. Warnings/Information on intentional patterns
  # (unapproved verbs on private script functions, Invoke-Expression in a
  # stack-neutral runner, empty catch blocks in best-effort hooks, Write-Host
  # in interactive bootstrap, etc.) would otherwise pin CI red without buying
  # safety. The dedicated psanalyze job in scaffold-self-check.yml uses these
  # same settings.
  Severity = @('Error')
  ExcludeRules = @(
    'PSUseApprovedVerbs',
    'PSAvoidUsingInvokeExpression',
    'PSAvoidUsingEmptyCatchBlock',
    'PSAvoidUsingWriteHost',
    'PSUseShouldProcessForStateChangingFunctions',
    'PSAvoidUsingPositionalParameters',
    'PSUseDeclaredVarsMoreThanAssignments',
    'PSUseSingularNouns',
    'PSPossibleIncorrectComparisonWithNull',
    'PSReviewUnusedParameter',
    'PSAvoidUsingCmdletAliases',
    'PSUseShouldProcessForStateChangingFunctions',
    'PSAvoidGlobalVars',
    'PSAvoidAssignmentToAutomaticVariable',
    'PSUseProcessBlockForPipelineCommand',
    'PSAvoidUsingDoubleQuotesForConstantString',
    'PSAvoidLongLines',
    'PSAvoidTrailingWhitespace',
    'PSAvoidSemicolonsAsLineTerminators',
    'PSUseCorrectCasing',
    'PSPlaceCloseBrace',
    'PSPlaceOpenBrace'
  )
}
