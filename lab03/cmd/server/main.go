package main

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintln(os.Stderr, "usage: server <server_port> <concurrency_level>")
		os.Exit(1)
	}
	port := os.Args[1]
	if _, err := strconv.Atoi(port); err != nil || port == "" {
		fmt.Fprintln(os.Stderr, "invalid port")
		os.Exit(1)
	}
	limit, err := strconv.Atoi(os.Args[2])
	if err != nil || limit < 1 {
		fmt.Fprintln(os.Stderr, "invalid concurrency_level (need integer >= 1)")
		os.Exit(1)
	}
	sem := make(chan struct{}, limit)

	root, err := os.Getwd()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	ln, err := net.Listen("tcp", ":"+port)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer ln.Close()

	for {
		conn, err := ln.Accept()
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			continue
		}
		go func(c net.Conn) {
			defer c.Close()
			sem <- struct{}{}
			defer func() { <-sem }()
			if err := serveOne(c, root); err != nil {
				fmt.Fprintln(os.Stderr, err)
			}
		}(conn)
	}
}

func serveOne(conn net.Conn, root string) error {
	br := bufio.NewReader(conn)

	line, err := br.ReadString('\n')
	if err != nil {
		return err
	}
	method, urlPath, ok := parseRequestLine(line)
	if !ok || !strings.EqualFold(method, "GET") {
		_, werr := writeStatus(conn, 400, "Bad Request", "text/plain; charset=utf-8", []byte("Bad Request"))
		return werr
	}

	if err := consumeHeaders(br); err != nil {
		return err
	}

	fullPath, err := resolveSafePath(root, urlPath)
	if err != nil {
		if errors.Is(err, errUnsafePath) {
			_, werr := writeStatus(conn, 403, "Forbidden", "text/plain; charset=utf-8", []byte("Forbidden"))
			return werr
		}
		return err
	}

	data, err := os.ReadFile(fullPath)
	if err != nil {
		if os.IsNotExist(err) {
			_, werr := writeStatus(conn, 404, "Not Found", "text/plain; charset=utf-8", []byte("404 Not Found"))
			return werr
		}
		_, werr := writeStatus(conn, 500, "Internal Server Error", "text/plain; charset=utf-8", []byte("Internal Server Error"))
		return werr
	}

	ct := mime.TypeByExtension(filepath.Ext(fullPath))
	if ct == "" {
		ct = "application/octet-stream"
	}
	_, err = writeStatus(conn, 200, "OK", ct, data)
	return err
}

func parseRequestLine(line string) (method, path string, ok bool) {
	line = strings.TrimRight(line, "\r\n")
	fields := strings.Fields(line)
	if len(fields) < 2 {
		return "", "", false
	}
	return fields[0], fields[1], true
}

func consumeHeaders(br *bufio.Reader) error {
	for {
		line, err := br.ReadString('\n')
		if err != nil {
			return err
		}
		if line == "\r\n" || line == "\n" {
			break
		}
	}
	return nil
}

var errUnsafePath = errors.New("unsafe path")

func resolveSafePath(root, raw string) (string, error) {
	raw = strings.SplitN(raw, "?", 2)[0]
	unescaped, err := url.PathUnescape(raw)
	if err != nil {
		unescaped = raw
	}
	p := strings.TrimPrefix(unescaped, "/")
	if p == "" || p == "." {
		p = "index.html"
	}
	clean := filepath.Clean(p)
	if clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", errUnsafePath
	}
	full := filepath.Join(root, clean)
	rel, err := filepath.Rel(root, full)
	if err != nil || strings.HasPrefix(rel, "..") {
		return "", errUnsafePath
	}
	return full, nil
}

func writeStatus(w io.Writer, code int, reason, contentType string, body []byte) (int, error) {
	statusLine := fmt.Sprintf("HTTP/1.0 %d %s\r\n", code, reason)
	headers := fmt.Sprintf(
		"Content-Length: %d\r\nContent-Type: %s\r\nConnection: close\r\n\r\n",
		len(body), contentType,
	)
	n1, err := io.WriteString(w, statusLine)
	if err != nil {
		return n1, err
	}
	n2, err := io.WriteString(w, headers)
	n1 += n2
	if err != nil {
		return n1, err
	}
	n3, err := w.Write(body)
	return n1 + n3, err
}
