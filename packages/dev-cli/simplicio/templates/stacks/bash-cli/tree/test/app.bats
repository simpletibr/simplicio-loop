@test "prints ok by default" {
  run bash bin/app.sh
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}

@test "prints help" {
  run bash bin/app.sh --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"{project_name}"* ]]
}
