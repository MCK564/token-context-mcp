package server

import (
	"fmt"
	str "strings"
	_ "net/http/pprof"
	"github.com/acme/util"
)

type Handler interface {
	Serve(req Request) error
}

type Server struct {
	name string
	h    Handler
}

type ID int

type Alias = map[string]int

func NewServer(name string) *Server {
	return &Server{name: name}
}

func (s *Server) Start() error {
	fmt.Println(str.ToUpper(s.name))
	s.helper()
	util.Log("x")
	return s.h.Serve(Request{})
}

func (s Server) helper() {}

func (s *Server) Stop() { NewServer("a") }
