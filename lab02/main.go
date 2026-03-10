package main

import (
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strconv"
	"sync"
)

type Product struct {
	ID          int    `json:"id"`
	Name        string `json:"name"`
	Description string `json:"description"`
}

type CreateProductRequest struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

type UpdateProductRequest struct {
	Name        *string `json:"name,omitempty"`
	Description *string `json:"description,omitempty"`
}

type ErrorResponse struct {
	Error string `json:"error"`
}

type store struct {
	mu      sync.RWMutex
	products map[int]Product
	nextID  int
}

func newStore() *store {
	return &store{
		products: make(map[int]Product),
		nextID:  1,
	}
}

func (s *store) Add(p Product) Product {
	s.mu.Lock()
	defer s.mu.Unlock()
	p.ID = s.nextID
	s.nextID++
	s.products[p.ID] = p
	return p
}

func (s *store) Get(id int) (Product, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	p, ok := s.products[id]
	return p, ok
}

func (s *store) Update(id int, upd UpdateProductRequest) (Product, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.products[id]
	if !ok {
		return Product{}, false
	}
	if upd.Name != nil {
		p.Name = *upd.Name
	}
	if upd.Description != nil {
		p.Description = *upd.Description
	}
	s.products[id] = p
	return p, true
}

func (s *store) Delete(id int) (Product, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.products[id]
	if !ok {
		return Product{}, false
	}
	delete(s.products, id)
	return p, true
}

func (s *store) All() []Product {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Product, 0, len(s.products))
	for _, p := range s.products {
		out = append(out, p)
	}
	return out
}

var st = newStore()

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, ErrorResponse{Error: msg})
}

func productIDFromRequest(r *http.Request) (int, error) {
	idStr := r.PathValue("id")
	if idStr == "" {
		return 0, errors.New("missing id")
	}
	id, err := strconv.Atoi(idStr)
	if err != nil || id < 1 {
		return 0, errors.New("invalid id")
	}
	return id, nil
}

func handlePostProduct(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Content-Type") != "application/json" {
		writeError(w, http.StatusBadRequest, "Content-Type must be application/json")
		return
	}
	var req CreateProductRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid JSON")
		return
	}
	p := st.Add(Product{Name: req.Name, Description: req.Description})
	writeJSON(w, http.StatusCreated, p)
}

func handleGetProduct(w http.ResponseWriter, r *http.Request) {
	id, err := productIDFromRequest(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	p, ok := st.Get(id)
	if !ok {
		writeError(w, http.StatusNotFound, "Product not found")
		return
	}
	writeJSON(w, http.StatusOK, p)
}

func handlePutProduct(w http.ResponseWriter, r *http.Request) {
	id, err := productIDFromRequest(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if r.Header.Get("Content-Type") != "application/json" {
		writeError(w, http.StatusBadRequest, "Content-Type must be application/json")
		return
	}
	var req UpdateProductRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid JSON")
		return
	}
	p, ok := st.Update(id, req)
	if !ok {
		writeError(w, http.StatusNotFound, "Product not found")
		return
	}
	writeJSON(w, http.StatusOK, p)
}

func handleDeleteProduct(w http.ResponseWriter, r *http.Request) {
	id, err := productIDFromRequest(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	p, ok := st.Delete(id)
	if !ok {
		writeError(w, http.StatusNotFound, "Product not found")
		return
	}
	writeJSON(w, http.StatusOK, p)
}

func handleGetProducts(w http.ResponseWriter, _ *http.Request) {
	products := st.All()
	if products == nil {
		products = []Product{}
	}
	writeJSON(w, http.StatusOK, products)
}

func main() {
	mux := http.NewServeMux()

	mux.HandleFunc("POST /product", handlePostProduct)
	mux.HandleFunc("GET /products", handleGetProducts)
	mux.HandleFunc("GET /product/{id}", handleGetProduct)
	mux.HandleFunc("PUT /product/{id}", handlePutProduct)
	mux.HandleFunc("DELETE /product/{id}", handleDeleteProduct)

	addr := ":8080"
	log.Printf("Product service listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}
