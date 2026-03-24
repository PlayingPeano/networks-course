package main

import (
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	if len(os.Args) != 4 {
		fmt.Fprintln(os.Stderr, "usage: client <server_host> <server_port> <filename>")
		os.Exit(1)
	}
	host := os.Args[1]
	port := os.Args[2]
	filename := os.Args[3]

	addr := net.JoinHostPort(host, port)
	conn, err := net.Dial("tcp", addr)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer conn.Close()

	path := buildRequestPath(filename)
	req := fmt.Sprintf(
		"GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: lab03-client\r\nConnection: close\r\n\r\n",
		path, host,
	)
	if _, err := conn.Write([]byte(req)); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	if _, err := io.Copy(os.Stdout, conn); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func buildRequestPath(filename string) string {
	p := strings.TrimSpace(filename)
	p = filepath.ToSlash(p)
	p = strings.TrimPrefix(p, "/")
	if p == "" {
		return "/"
	}
	parts := strings.Split(p, "/")
	for i := range parts {
		parts[i] = url.PathEscape(parts[i])
	}
	return "/" + strings.Join(parts, "/")
}
