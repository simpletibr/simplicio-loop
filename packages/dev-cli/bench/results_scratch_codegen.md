# Scratch Codegen Benchmark

deterministic executor benchmark plus live scratch-corpus evidence; synthetic cases validate individual executors while the live gate proves release-corpus mechanical-task metrics

## Summary

- cases: 90/90 passed
- codegen share: 100.00%
- expected executor match: 100.00%
- avg codegen latency: 51 ms
- post-validated cases: 90
- post-validation failures: 0
- planner calls: 0
- llm calls: 0

## Release Gate Status

- fifty_runs: True
- mechanical_share_ge_30: True
- executor_pass_rate_100: True
- executor_pass_rate_ge_llm: True
- typescript_next_route_compiles_and_responds_json: True
- llm_baseline_present: True
- latency_reduction_ge_50: True
- real_50_scratch_corpus: True
- real_mechanical_share_ge_30: True
- real_e2e_green_ge_80: True
- real_executor_pass_rate_ge_llm: None
- real_latency_reduction_ge_50: None
- zero_feature_regression_live: True

## LLM Baseline

- source: bench/results_scratch_live_gate_codegen_disabled_baseline.json (--disable-codegen live gate)
- cases: 10
- pass rate: 71.43%
- avg LLM latency: 154888 ms
- executor pass-rate >= LLM: True
- latency reduction: 99.97%

## Live Scratch Corpus

- source: bench/results_scratch_live_gate.json
- runs: 75/75 e2e green
- tasks: 135/135 codegen
- task-level LLM calls: 0
- codegen share: 100.00%
- avg live codegen latency: 61 ms
- stacks: go-gin, php-laravel, py-fastapi, rust-axum, ts-nextjs
- live latency reduction vs task-level LLM baseline: 99.96%

## Cases

| case | stack | executor | mode | post-validation | passed | duration_ms |
| --- | --- | --- | --- | --- | --- | ---: |
| python-orm-field r01 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 178 |
| python-pydantic-schema r01 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 4 |
| python-fastapi-route r01 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 2 |
| python-pytest-test r01 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 4 |
| typescript-next-route r01 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 491 |
| typescript-next-page r01 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 1 |
| go-gin-crud r01 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 1 |
| rust-axum-crud r01 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r01 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
| python-orm-field r02 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 5 |
| python-pydantic-schema r02 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 3 |
| python-fastapi-route r02 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 2 |
| python-pytest-test r02 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 4 |
| typescript-next-route r02 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 430 |
| typescript-next-page r02 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 1 |
| go-gin-crud r02 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 0 |
| rust-axum-crud r02 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r02 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
| python-orm-field r03 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 4 |
| python-pydantic-schema r03 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 3 |
| python-fastapi-route r03 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 3 |
| python-pytest-test r03 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 2 |
| typescript-next-route r03 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 378 |
| typescript-next-page r03 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 1 |
| go-gin-crud r03 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 1 |
| rust-axum-crud r03 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r03 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
| python-orm-field r04 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 4 |
| python-pydantic-schema r04 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 4 |
| python-fastapi-route r04 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 2 |
| python-pytest-test r04 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 3 |
| typescript-next-route r04 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 468 |
| typescript-next-page r04 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 2 |
| go-gin-crud r04 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 1 |
| rust-axum-crud r04 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r04 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
| python-orm-field r05 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 5 |
| python-pydantic-schema r05 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 3 |
| python-fastapi-route r05 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 2 |
| python-pytest-test r05 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 2 |
| typescript-next-route r05 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 412 |
| typescript-next-page r05 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 1 |
| go-gin-crud r05 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 0 |
| rust-axum-crud r05 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r05 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
| python-orm-field r06 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 4 |
| python-pydantic-schema r06 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 4 |
| python-fastapi-route r06 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 2 |
| python-pytest-test r06 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 3 |
| typescript-next-route r06 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 421 |
| typescript-next-page r06 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 1 |
| go-gin-crud r06 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 0 |
| rust-axum-crud r06 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r06 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
| python-orm-field r07 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 5 |
| python-pydantic-schema r07 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 3 |
| python-fastapi-route r07 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 1 |
| python-pytest-test r07 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 2 |
| typescript-next-route r07 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 418 |
| typescript-next-page r07 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 1 |
| go-gin-crud r07 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 0 |
| rust-axum-crud r07 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r07 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
| python-orm-field r08 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 4 |
| python-pydantic-schema r08 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 3 |
| python-fastapi-route r08 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 2 |
| python-pytest-test r08 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 3 |
| typescript-next-route r08 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 402 |
| typescript-next-page r08 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 1 |
| go-gin-crud r08 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 0 |
| rust-axum-crud r08 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r08 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
| python-orm-field r09 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 4 |
| python-pydantic-schema r09 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 3 |
| python-fastapi-route r09 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 2 |
| python-pytest-test r09 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 3 |
| typescript-next-route r09 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 431 |
| typescript-next-page r09 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 1 |
| go-gin-crud r09 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 1 |
| rust-axum-crud r09 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r09 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
| python-orm-field r10 | py-fastapi | python-add-orm-field | codegen | user_class,email_field,mapped_type | True | 4 |
| python-pydantic-schema r10 | py-fastapi | python-add-pydantic-schema | codegen | user_create,user_update,user_read | True | 3 |
| python-fastapi-route r10 | py-fastapi | python-add-fastapi-route | codegen | router_get,path_param,async_handler | True | 2 |
| python-pytest-test r10 | py-fastapi | python-add-pytest-test | codegen | imports_double,assertion,test_function | True | 2 |
| typescript-next-route r10 | ts-nextjs | typescript-add-next-route | codegen | typescript_compile,get_json,post_json | True | 424 |
| typescript-next-page r10 | ts-nextjs | typescript-add-next-page | codegen | crud_page_marker,async_page_component,create_form,list_render | True | 1 |
| go-gin-crud r10 | go-gin | go-gin-crud | codegen | package_http,gin_import,router_ctor,route_prefix,json_response | True | 0 |
| rust-axum-crud r10 | rust-axum | rust-axum-crud | codegen | axum_import,item_type,router,route_prefix,route_test | True | 0 |
| php-laravel-routes r10 | php-laravel | php-laravel-crud-routes | codegen | php_open,route_get,route_post,json_response,created_status | True | 0 |
