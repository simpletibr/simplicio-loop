package main

import (
	"log"

	apphttp "{project_name}/internal/http"
)

func main() {
	router := apphttp.NewRouter()
	if err := router.Run(":8080"); err != nil {
		log.Fatal(err)
	}
}
