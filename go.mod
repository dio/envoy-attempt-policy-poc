module github.com/dio/envoy-attempt-policy-poc

go 1.25.6

require github.com/envoyproxy/envoy/source/extensions/dynamic_modules v0.0.0

replace github.com/envoyproxy/envoy/source/extensions/dynamic_modules => ./build/envoy/source/extensions/dynamic_modules
