package main

import (
	"log"

	"{project_name}/internal/http"
)

func main() {
	if err := http.NewRouter().Start(":8080"); err != nil {
		log.Fatal(err)
	}
}
