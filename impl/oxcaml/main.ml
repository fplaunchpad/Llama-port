(* microgpt inference - OCaml / OxCaml port.

   Implements the contract in BENCHMARK.md: same weights, same f64 operation order,
   same xorshift64* RNG, same JSON report as the Python, C++ and Rust ports.

   Build (OxCaml switch, flambda2 backend):
     ocamlopt -O3 -I +unix unix.cmxa main.ml -o build/microgpt_infer

   OCaml notes relevant to the numerics contract:
     - [float] is IEEE double, and [float array] is unboxed and flat, so the layout
       matches the other ports with no special effort.
     - There is no compensated [sum] in the stdlib, and the accumulator loops below
       are written explicitly as left-to-right folds, so BENCHMARK.md section 3 is
       satisfied by construction. (See PORTING.md trap 1 for why that matters.)
     - OCaml never contracts [a *. b +. c] into an FMA, so nothing to disable.
     - [**] is [pow], which is what rmsnorm and the attention scale require. *)

(* ------------------------------------------------------------------ sha256 *)

let sha256_k =
  [| 0x428a2f98l; 0x71374491l; 0xb5c0fbcfl; 0xe9b5dba5l; 0x3956c25bl; 0x59f111f1l;
     0x923f82a4l; 0xab1c5ed5l; 0xd807aa98l; 0x12835b01l; 0x243185bel; 0x550c7dc3l;
     0x72be5d74l; 0x80deb1fel; 0x9bdc06a7l; 0xc19bf174l; 0xe49b69c1l; 0xefbe4786l;
     0x0fc19dc6l; 0x240ca1ccl; 0x2de92c6fl; 0x4a7484aal; 0x5cb0a9dcl; 0x76f988dal;
     0x983e5152l; 0xa831c66dl; 0xb00327c8l; 0xbf597fc7l; 0xc6e00bf3l; 0xd5a79147l;
     0x06ca6351l; 0x14292967l; 0x27b70a85l; 0x2e1b2138l; 0x4d2c6dfcl; 0x53380d13l;
     0x650a7354l; 0x766a0abbl; 0x81c2c92el; 0x92722c85l; 0xa2bfe8a1l; 0xa81a664bl;
     0xc24b8b70l; 0xc76c51a3l; 0xd192e819l; 0xd6990624l; 0xf40e3585l; 0x106aa070l;
     0x19a4c116l; 0x1e376c08l; 0x2748774cl; 0x34b0bcb5l; 0x391c0cb3l; 0x4ed8aa4al;
     0x5b9cca4fl; 0x682e6ff3l; 0x748f82eel; 0x78a5636fl; 0x84c87814l; 0x8cc70208l;
     0x90befffal; 0xa4506cebl; 0xbef9a3f7l; 0xc67178f2l |]

let rotr32 x n = Int32.logor (Int32.shift_right_logical x n) (Int32.shift_left x (32 - n))

let sha256_hex (data : string) =
  let h = [| 0x6a09e667l; 0xbb67ae85l; 0x3c6ef372l; 0xa54ff53al;
             0x510e527fl; 0x9b05688cl; 0x1f83d9abl; 0x5be0cd19l |] in
  let len = String.length data in
  let bitlen = Int64.mul (Int64.of_int len) 8L in
  (* message + 0x80 + zero padding to 56 mod 64 + 8 length bytes *)
  let padded_len =
    let n = len + 1 in
    let rem = n mod 64 in
    let pad = if rem <= 56 then 56 - rem else 120 - rem in
    n + pad + 8
  in
  let msg = Bytes.make padded_len '\000' in
  Bytes.blit_string data 0 msg 0 len;
  Bytes.set msg len '\x80';
  Bytes.set_int64_be msg (padded_len - 8) bitlen;
  let w = Array.make 64 0l in
  let nblocks = padded_len / 64 in
  for b = 0 to nblocks - 1 do
    let off = b * 64 in
    for i = 0 to 15 do
      w.(i) <- Bytes.get_int32_be msg (off + i * 4)
    done;
    for i = 16 to 63 do
      let s0 =
        Int32.logxor (Int32.logxor (rotr32 w.(i - 15) 7) (rotr32 w.(i - 15) 18))
          (Int32.shift_right_logical w.(i - 15) 3)
      in
      let s1 =
        Int32.logxor (Int32.logxor (rotr32 w.(i - 2) 17) (rotr32 w.(i - 2) 19))
          (Int32.shift_right_logical w.(i - 2) 10)
      in
      w.(i) <- Int32.add (Int32.add w.(i - 16) s0) (Int32.add w.(i - 7) s1)
    done;
    let a = ref h.(0) and b' = ref h.(1) and c = ref h.(2) and d = ref h.(3) in
    let e = ref h.(4) and f = ref h.(5) and g = ref h.(6) and hh = ref h.(7) in
    for i = 0 to 63 do
      let s1 =
        Int32.logxor (Int32.logxor (rotr32 !e 6) (rotr32 !e 11)) (rotr32 !e 25)
      in
      let ch = Int32.logxor (Int32.logand !e !f) (Int32.logand (Int32.lognot !e) !g) in
      let t1 =
        Int32.add (Int32.add (Int32.add !hh s1) (Int32.add ch sha256_k.(i))) w.(i)
      in
      let s0 =
        Int32.logxor (Int32.logxor (rotr32 !a 2) (rotr32 !a 13)) (rotr32 !a 22)
      in
      let maj =
        Int32.logxor
          (Int32.logxor (Int32.logand !a !b') (Int32.logand !a !c))
          (Int32.logand !b' !c)
      in
      let t2 = Int32.add s0 maj in
      hh := !g; g := !f; f := !e; e := Int32.add !d t1;
      d := !c; c := !b'; b' := !a; a := Int32.add t1 t2
    done;
    h.(0) <- Int32.add h.(0) !a; h.(1) <- Int32.add h.(1) !b';
    h.(2) <- Int32.add h.(2) !c; h.(3) <- Int32.add h.(3) !d;
    h.(4) <- Int32.add h.(4) !e; h.(5) <- Int32.add h.(5) !f;
    h.(6) <- Int32.add h.(6) !g; h.(7) <- Int32.add h.(7) !hh
  done;
  let buf = Buffer.create 64 in
  Array.iter (fun v -> Buffer.add_string buf (Printf.sprintf "%08lx" v)) h;
  Buffer.contents buf

(* --------------------------------------------------------------------- rng *)

type rng = { mutable state : int64 }

let rng_make (seed : int64) =
  { state = (if Int64.equal seed 0L then 0x9E3779B97F4A7C15L else seed) }

let next_u64 r =
  let x = r.state in
  let x = Int64.logxor x (Int64.shift_right_logical x 12) in
  let x = Int64.logxor x (Int64.shift_left x 25) in
  let x = Int64.logxor x (Int64.shift_right_logical x 27) in
  r.state <- x;
  Int64.mul x 0x2545F4914F6CDD1DL

let next_f64 r =
  (* the shift leaves 53 bits, which Int64.to_float converts exactly *)
  Int64.to_float (Int64.shift_right_logical (next_u64 r) 11) *. (1.0 /. 9007199254740992.0)

let fnv1a64 (s : string) =
  let h = ref 0xCBF29CE484222325L in
  String.iter
    (fun ch ->
      h := Int64.logxor !h (Int64.of_int (Char.code ch));
      h := Int64.mul !h 0x100000001B3L)
    s;
  !h

(* ----------------------------------------------------------------- weights *)

type mat = { rows : int; cols : int; d : float array }

type layer = { wq : mat; wk : mat; wv : mat; wo : mat; fc1 : mat; fc2 : mat }

type model = {
  n_layer : int;
  n_embd : int;
  block_size : int;
  n_head : int;
  vocab_size : int;
  head_dim : int;
  bos : int;
  uchars : string;
  char_to_id : int array;
  wte : mat;
  wpe : mat;
  lm_head : mat;
  layers : layer array;
  attn_scale : float;
  num_weights : int;
  weights_sum : float;
  weights_abs_sum : float;
  sha256 : string;
}

let rd_u32 (s : string) off = Int32.to_int (String.get_int32_le s off) land 0xFFFFFFFF

let load_model path =
  let blob =
    let ic = open_in_bin path in
    let n = in_channel_length ic in
    let b = really_input_string ic n in
    close_in ic; b
  in
  if String.length blob < 32 || String.sub blob 0 4 <> "MGPT" then
    failwith ("bad magic, not a microgpt-bin file: " ^ path);
  let sha = sha256_hex blob in
  let version = rd_u32 blob 4 in
  if version <> 1 then failwith (Printf.sprintf "unsupported format version %d" version);
  let n_layer = rd_u32 blob 8 in
  let n_embd = rd_u32 blob 12 in
  let block_size = rd_u32 blob 16 in
  let n_head = rd_u32 blob 20 in
  let vocab_size = rd_u32 blob 24 in
  let n_uchars = rd_u32 blob 28 in
  let uchars = String.sub blob 32 n_uchars in
  let off = ref (32 + n_uchars) in
  off := !off + ((8 - (!off mod 8)) mod 8);   (* align the f64 payload *)
  let char_to_id = Array.make 256 (-1) in
  String.iteri (fun i c -> char_to_id.(Char.code c) <- i) uchars;

  (* Plain running totals, matching the exporter and the other ports. *)
  let wsum = ref 0.0 and wabs = ref 0.0 and count = ref 0 in
  let cursor = ref !off in
  let take rows cols =
    let n = rows * cols in
    let d = Array.make n 0.0 in
    for i = 0 to n - 1 do
      if !cursor + 8 > String.length blob then failwith "weight file truncated";
      let v = Int64.float_of_bits (String.get_int64_le blob !cursor) in
      cursor := !cursor + 8;
      d.(i) <- v;
      wsum := !wsum +. v;
      wabs := !wabs +. Float.abs v;
      incr count
    done;
    { rows; cols; d }
  in
  let wte = take vocab_size n_embd in
  let wpe = take block_size n_embd in
  let lm_head = take vocab_size n_embd in
  let layers =
    Array.init n_layer (fun _ ->
        let wq = take n_embd n_embd in
        let wk = take n_embd n_embd in
        let wv = take n_embd n_embd in
        let wo = take n_embd n_embd in
        let fc1 = take (4 * n_embd) n_embd in
        let fc2 = take n_embd (4 * n_embd) in
        { wq; wk; wv; wo; fc1; fc2 })
  in
  if !cursor <> String.length blob then
    failwith "weight file has trailing bytes the model does not want";
  let head_dim = n_embd / n_head in
  {
    n_layer; n_embd; block_size; n_head; vocab_size; head_dim;
    bos = n_uchars; uchars; char_to_id;
    wte; wpe; lm_head; layers;
    attn_scale = float_of_int head_dim ** 0.5;
    num_weights = !count; weights_sum = !wsum; weights_abs_sum = !wabs; sha256 = sha;
  }

let tokenize m doc =
  let n = String.length doc in
  let t = Array.make (n + 2) m.bos in
  String.iteri
    (fun i c ->
      let id = m.char_to_id.(Char.code c) in
      if id < 0 then failwith (Printf.sprintf "character not in vocab: %c" c);
      t.(i + 1) <- id)
    doc;
  t

(* ----------------------------------------------------------------- kernels
   Operation order here is load-bearing: see BENCHMARK.md section 3. The folds
   are written as explicit left-to-right recursions so that no library routine
   can substitute a compensated or pairwise summation. *)

(* Four independent accumulators, so the CPU has four separate add chains to overlap.
   Each row still accumulates strictly left to right, so this is the same arithmetic
   in the same order - only the interleaving changes, and the output hash is unchanged.

   This matters far more in OCaml than in C++: GCC already interleaves output rows by
   itself, but the OCaml backend does not, leaving each dot product as a serial chain of
   dependent f64 adds (~4 cycles each). Measured +61% on generation. *)
let linear (x : float array) (w : mat) (out : float array) =
  let cols = w.cols and rows = w.rows and d = w.d in
  let o = ref 0 in
  while !o + 4 <= rows do
    let b0 = !o * cols in
    let b1 = b0 + cols and b2 = b0 + (2 * cols) and b3 = b0 + (3 * cols) in
    let a0 = ref 0.0 and a1 = ref 0.0 and a2 = ref 0.0 and a3 = ref 0.0 in
    for i = 0 to cols - 1 do
      let xi = x.(i) in
      a0 := !a0 +. (d.(b0 + i) *. xi);
      a1 := !a1 +. (d.(b1 + i) *. xi);
      a2 := !a2 +. (d.(b2 + i) *. xi);
      a3 := !a3 +. (d.(b3 + i) *. xi)
    done;
    out.(!o) <- !a0;
    out.(!o + 1) <- !a1;
    out.(!o + 2) <- !a2;
    out.(!o + 3) <- !a3;
    o := !o + 4
  done;
  while !o < rows do
    let base = !o * cols in
    let acc = ref 0.0 in
    for i = 0 to cols - 1 do
      acc := !acc +. (d.(base + i) *. x.(i))
    done;
    out.(!o) <- !acc;
    incr o
  done

let rmsnorm_scale (x : float array) n =
  let rec go i acc = if i >= n then acc else go (i + 1) (acc +. (x.(i) *. x.(i))) in
  let ms = go 0 0.0 /. float_of_int n in
  (ms +. 1e-5) ** -0.5

let rmsnorm_inplace (x : float array) n =
  let s = rmsnorm_scale x n in
  for i = 0 to n - 1 do x.(i) <- x.(i) *. s done

let rmsnorm_to (x : float array) (out : float array) n =
  let s = rmsnorm_scale x n in
  for i = 0 to n - 1 do out.(i) <- x.(i) *. s done

let softmax (z : float array) n =
  let mx = ref z.(0) in
  for i = 1 to n - 1 do if z.(i) > !mx then mx := z.(i) done;
  let m = !mx in
  let total = ref 0.0 in
  for i = 0 to n - 1 do
    let e = exp (z.(i) -. m) in
    z.(i) <- e;
    total := !total +. e
  done;
  let t = !total in
  for i = 0 to n - 1 do z.(i) <- z.(i) /. t done

let sample_from (probs : float array) n r (cum : float array) =
  let total = ref 0.0 in
  for i = 0 to n - 1 do
    total := !total +. probs.(i);
    cum.(i) <- !total
  done;
  let u = next_f64 r *. !total in
  let rec scan i = if i >= n then n - 1 else if u < cum.(i) then i else scan (i + 1) in
  scan 0

(* ------------------------------------------------------------------- state *)

type cache = {
  keys : float array array;   (* per layer, block_size * n_embd, flat *)
  values : float array array;
  mutable len : int;
}

let cache_make m =
  {
    keys = Array.init m.n_layer (fun _ -> Array.make (m.block_size * m.n_embd) 0.0);
    values = Array.init m.n_layer (fun _ -> Array.make (m.block_size * m.n_embd) 0.0);
    len = 0;
  }

type scratch = {
  x : float array; xn : float array; q : float array; k : float array; v : float array;
  attn : float array; hidden : float array; logits : float array;
  attn_logits : float array; probs : float array; cum : float array;
}

let scratch_make m =
  {
    x = Array.make m.n_embd 0.0;
    xn = Array.make m.n_embd 0.0;
    q = Array.make m.n_embd 0.0;
    k = Array.make m.n_embd 0.0;
    v = Array.make m.n_embd 0.0;
    attn = Array.make m.n_embd 0.0;
    hidden = Array.make (4 * m.n_embd) 0.0;
    logits = Array.make m.vocab_size 0.0;
    attn_logits = Array.make m.block_size 0.0;
    probs = Array.make m.vocab_size 0.0;
    cum = Array.make m.vocab_size 0.0;
  }

(* One decode step. Appends this position's k/v to the cache, leaves logits in s.logits. *)
let forward m token_id pos_id c s =
  let e = m.n_embd and hd = m.head_dim in
  let tok_base = token_id * e and pos_base = pos_id * e in
  for i = 0 to e - 1 do
    s.x.(i) <- m.wte.d.(tok_base + i) +. m.wpe.d.(pos_base + i)
  done;
  rmsnorm_inplace s.x e;

  let t_idx = c.len in
  let t_len = t_idx + 1 in
  for li = 0 to m.n_layer - 1 do
    let layer = m.layers.(li) in
    rmsnorm_to s.x s.xn e;
    linear s.xn layer.wq s.q;
    linear s.xn layer.wk s.k;
    linear s.xn layer.wv s.v;

    let kcache = c.keys.(li) and vcache = c.values.(li) in
    Array.blit s.k 0 kcache (t_idx * e) e;
    Array.blit s.v 0 vcache (t_idx * e) e;

    let scale = m.attn_scale in
    for h = 0 to m.n_head - 1 do
      let hs = h * hd in
      for t = 0 to t_len - 1 do
        let kbase = (t * e) + hs in
        let rec go j acc =
          if j >= hd then acc else go (j + 1) (acc +. (s.q.(hs + j) *. kcache.(kbase + j)))
        in
        s.attn_logits.(t) <- go 0 0.0 /. scale
      done;
      softmax s.attn_logits t_len;
      for j = 0 to hd - 1 do
        let rec go t acc =
          if t >= t_len then acc
          else go (t + 1) (acc +. (s.attn_logits.(t) *. vcache.((t * e) + hs + j)))
        in
        s.attn.(hs + j) <- go 0 0.0
      done
    done;
    linear s.attn layer.wo s.xn;
    for i = 0 to e - 1 do s.x.(i) <- s.x.(i) +. s.xn.(i) done;

    rmsnorm_to s.x s.xn e;
    linear s.xn layer.fc1 s.hidden;
    for i = 0 to (4 * e) - 1 do
      (* written as `x > 0 ? x : 0` so that NaN maps to 0, matching the contract *)
      s.hidden.(i) <- (if s.hidden.(i) > 0.0 then s.hidden.(i) else 0.0)
    done;
    linear s.hidden layer.fc2 s.xn;
    for i = 0 to e - 1 do s.x.(i) <- s.x.(i) +. s.xn.(i) done
  done;
  c.len <- t_len;
  linear s.x m.lm_head s.logits

(* -------------------------------------------------------------- benchmarks *)

(* Generate one sample. Returns the number of forward passes it took. *)
let gen_one m temperature r s c (out : Buffer.t option) =
  c.len <- 0;
  let token_id = ref m.bos in
  let n = ref 0 in
  (try
     for pos = 0 to m.block_size - 1 do
       forward m !token_id pos c s;
       incr n;
       for i = 0 to m.vocab_size - 1 do
         (* divide, never a precomputed reciprocal *)
         s.probs.(i) <- s.logits.(i) /. temperature
       done;
       softmax s.probs m.vocab_size;
       token_id := sample_from s.probs m.vocab_size r s.cum;
       if !token_id = m.bos then raise Exit;
       match out with
       | Some b -> Buffer.add_char b m.uchars.[!token_id]
       | None -> ()
     done
   with Exit -> ());
  !n

(* Teacher-forced scoring of one document. Returns tokens scored; adds into !nll.
   The per-document local accumulator is required: folding every token into one
   running total sums in a different order (PORTING.md trap 3). *)
let score_doc m doc s c (nll : float ref option) =
  let t = tokenize m doc in
  let n = min m.block_size (Array.length t - 1) in
  c.len <- 0;
  let local = ref 0.0 in
  for pos = 0 to n - 1 do
    forward m t.(pos) pos c s;
    Array.blit s.logits 0 s.probs 0 m.vocab_size;
    softmax s.probs m.vocab_size;
    local := !local -. log s.probs.(t.(pos + 1))
  done;
  (match nll with Some acc -> acc := !acc +. !local | None -> ());
  n

(* -------------------------------------------------------------------- json *)

let json_escape s =
  let b = Buffer.create (String.length s + 2) in
  Buffer.add_char b '"';
  String.iter
    (fun c ->
      match c with
      | '"' -> Buffer.add_string b "\\\""
      | '\\' -> Buffer.add_string b "\\\\"
      | '\n' -> Buffer.add_string b "\\n"
      | '\r' -> Buffer.add_string b "\\r"
      | '\t' -> Buffer.add_string b "\\t"
      | c when Char.code c < 0x20 -> Buffer.add_string b (Printf.sprintf "\\u%04x" (Char.code c))
      | c -> Buffer.add_char b c)
    s;
  Buffer.add_char b '"';
  Buffer.contents b

(* %.17g round-trips an IEEE double exactly, which is what the harness compares. *)
let jf v = if Float.is_finite v then Printf.sprintf "%.17g" v else "null"

type jw = { buf : Buffer.t; mutable first : bool list }

let jw_make () = { buf = Buffer.create 65536; first = [] }
let jcomma w =
  match w.first with
  | [] -> ()
  | f :: rest ->
      if not f then Buffer.add_char w.buf ',';
      w.first <- false :: rest
let jkey w k = jcomma w; Buffer.add_string w.buf (json_escape k); Buffer.add_char w.buf ':'
let jobj_start w = jcomma w; Buffer.add_char w.buf '{'; w.first <- true :: w.first
let jobj w k = jkey w k; Buffer.add_char w.buf '{'; w.first <- true :: w.first
let jobj_end w = Buffer.add_char w.buf '}'; w.first <- List.tl w.first
let jarr w k = jkey w k; Buffer.add_char w.buf '['; w.first <- true :: w.first
let jarr_end w = Buffer.add_char w.buf ']'; w.first <- List.tl w.first
let jnum w k v = jkey w k; Buffer.add_string w.buf (jf v)
let jint w k v = jkey w k; Buffer.add_string w.buf (string_of_int v)
let jstr w k v = jkey w k; Buffer.add_string w.buf (json_escape v)
let jvalf w v = jcomma w; Buffer.add_string w.buf (jf v)
let jvali w v = jcomma w; Buffer.add_string w.buf (string_of_int v)
let jvals w v = jcomma w; Buffer.add_string w.buf (json_escape v)

(* -------------------------------------------------------------------- main *)

let read_docs path max_docs =
  let ic = open_in path in
  let docs = ref [] and count = ref 0 in
  (try
     while max_docs <= 0 || !count < max_docs do
       let line = input_line ic in
       (* strip both ends, matching Python's str.strip() and the other ports *)
       let is_ws c = c = '\r' || c = '\n' || c = ' ' || c = '\t' in
       let n = String.length line in
       let b = ref 0 and e = ref n in
       while !b < !e && is_ws line.[!b] do incr b done;
       while !e > !b && is_ws line.[!e - 1] do decr e done;
       let t = String.sub line !b (!e - !b) in
       if String.length t > 0 then begin
         docs := t :: !docs;
         incr count
       end
     done
   with End_of_file -> ());
  close_in ic;
  Array.of_list (List.rev !docs)

let median (a : float array) =
  let b = Array.copy a in
  Array.sort compare b;
  b.(Array.length b / 2)

let () =
  let weights = ref "weights/microgpt.bin" in
  let data = ref "data/val.txt" in
  let mode = ref "all" in
  let json_out = ref "" in
  let samples = ref 1000 and seed = ref 1234 and repeats = ref 5 in
  let max_docs = ref 0 and _pin = ref 0 in
  let temperature = ref 0.5 and time_budget = ref 2.0 in
  let argv = Sys.argv in
  let n = Array.length argv in
  let i = ref 1 in
  (try
     while !i < n do
       let a = argv.(!i) in
       let next () =
         incr i;
         if !i >= n then failwith ("missing value for " ^ a);
         argv.(!i)
       in
       (match a with
        | "--weights" -> weights := next ()
        | "--data" -> data := next ()
        | "--mode" -> mode := next ()
        | "--json" -> json_out := next ()
        | "--samples" -> samples := int_of_string (next ())
        | "--seed" -> seed := int_of_string (next ())
        | "--repeats" -> repeats := int_of_string (next ())
        | "--max-docs" -> max_docs := int_of_string (next ())
        | "--pin" -> _pin := int_of_string (next ())
        | "--temperature" -> temperature := float_of_string (next ())
        | "--time-budget" -> time_budget := float_of_string (next ())
        | other -> failwith ("unknown argument: " ^ other));
       incr i
     done;

     if not (List.mem !mode [ "all"; "gen"; "ppl"; "check" ]) then
       failwith ("unknown --mode " ^ !mode);

     let t0 = Unix.gettimeofday () in
     let m = load_model !weights in
     let load_seconds = Unix.gettimeofday () -. t0 in
     let docs = read_docs !data !max_docs in
     let s = scratch_make m in
     let c = cache_make m in

     let do_check = !mode = "all" || !mode = "check" in
     let do_gen = !mode = "all" || !mode = "gen" in
     let do_ppl = !mode = "all" || !mode = "ppl" in

     let w = jw_make () in
     jobj_start w;
     jstr w "impl" "oxcaml";
     jstr w "mode" !mode;
     jstr w "runtime" ("OCaml " ^ Sys.ocaml_version);
     jstr w "build" "ocamlopt -O3 (flambda2); no fast-math equivalent exists in OCaml";
     jstr w "weights_sha256" m.sha256;
     jstr w "weights_path" !weights;
     jstr w "data_path" !data;
     jobj w "config";
     jint w "n_layer" m.n_layer;
     jint w "n_embd" m.n_embd;
     jint w "block_size" m.block_size;
     jint w "n_head" m.n_head;
     jint w "head_dim" m.head_dim;
     jint w "vocab_size" m.vocab_size;
     jint w "bos_token_id" m.bos;
     jstr w "uchars" m.uchars;
     jint w "num_weights" m.num_weights;
     jobj_end w;
     jnum w "load_seconds" load_seconds;
     (* OCaml has no stdlib affinity binding; pin externally with taskset. *)
     jstr w "cpu_pin" "external (taskset)";

     if do_check then begin
       let prompt = "emma" in
       let pt = tokenize m prompt in
       c.len <- 0;
       for pos = 0 to Array.length pt - 2 do
         forward m pt.(pos) pos c s
       done;
       let logits = Array.copy s.logits in
       let probs = Array.copy logits in
       softmax probs m.vocab_size;
       let argmax = ref 0 in
       for k = 1 to m.vocab_size - 1 do
         if probs.(k) > probs.(!argmax) then argmax := k
       done;
       let take3 = min 3 (Array.length docs) in
       let nll3 = ref 0.0 and n3 = ref 0 in
       for di = 0 to take3 - 1 do
         n3 := !n3 + score_doc m docs.(di) s c (Some nll3)
       done;
       let r = rng_make (Int64.of_int !seed) in
       let draws = Array.init 4 (fun _ -> next_u64 r) in

       jobj w "check";
       jstr w "prompt" prompt;
       jarr w "logits_after_prompt";
       Array.iter (fun v -> jvalf w v) logits;
       jarr_end w;
       jarr w "probs_after_prompt";
       Array.iter (fun v -> jvalf w v) probs;
       jarr_end w;
       jint w "argmax_token" !argmax;
       jstr w "argmax_char"
         (if !argmax = m.bos then "<BOS>" else String.make 1 m.uchars.[!argmax]);
       jarr w "first3_docs";
       for di = 0 to take3 - 1 do jvals w docs.(di) done;
       jarr_end w;
       jnum w "first3_nll" !nll3;
       jint w "first3_tokens" !n3;
       jint w "rng_seed" !seed;
       jarr w "rng_first4_u64";
       Array.iter (fun v -> jvals w (Printf.sprintf "0x%016Lx" v)) draws;
       jarr_end w;
       jnum w "weights_sum" m.weights_sum;
       jnum w "weights_abs_sum" m.weights_abs_sum;
       jobj_end w
     end;

     if do_gen then begin
       (* 1. Deterministic pass: fixed sample count, produces the cross-language hash.
             Doubles as warmup so the timed passes below start hot. *)
       let texts = Array.make !samples "" in
       let tokens = ref 0 and chars = ref 0 in
       let r = rng_make (Int64.of_int !seed) in
       for si = 0 to !samples - 1 do
         let b = Buffer.create 16 in
         tokens := !tokens + gen_one m !temperature r s c (Some b);
         texts.(si) <- Buffer.contents b;
         chars := !chars + String.length texts.(si)
       done;
       let body = String.concat "\n" (Array.to_list texts) in

       (* 2. Timed passes under a shared wall-clock budget. *)
       let rates = Array.make !repeats 0.0 in
       let tok_counts = Array.make !repeats 0 in
       let seconds = Array.make !repeats 0.0 in
       for rep = 0 to !repeats - 1 do
         let r = rng_make (Int64.of_int !seed) in
         let n_tok = ref 0 in
         let start = Unix.gettimeofday () in
         let elapsed = ref 0.0 in
         let continue_ = ref true in
         while !continue_ do
           n_tok := !n_tok + gen_one m !temperature r s c None;
           elapsed := Unix.gettimeofday () -. start;
           if !elapsed >= !time_budget then continue_ := false
         done;
         tok_counts.(rep) <- !n_tok;
         seconds.(rep) <- !elapsed;
         rates.(rep) <- float_of_int !n_tok /. !elapsed
       done;
       let sorted = Array.copy rates in
       Array.sort compare sorted;

       jobj w "gen";
       jint w "samples" !samples;
       jnum w "temperature" !temperature;
       jint w "seed" !seed;
       jint w "repeats" !repeats;
       jnum w "time_budget" !time_budget;
       jint w "tokens" !tokens;
       jint w "chars" !chars;
       jstr w "output_fnv1a64" (Printf.sprintf "0x%016Lx" (fnv1a64 body));
       jarr w "first_samples";
       for k = 0 to min 20 (Array.length texts) - 1 do jvals w texts.(k) done;
       jarr_end w;
       jarr w "rates_per_repeat";
       Array.iter (fun v -> jvalf w v) rates;
       jarr_end w;
       jarr w "tokens_per_repeat";
       Array.iter (fun v -> jvali w v) tok_counts;
       jarr_end w;
       jarr w "seconds_per_repeat";
       Array.iter (fun v -> jvalf w v) seconds;
       jarr_end w;
       jnum w "tokens_per_sec_best" sorted.(Array.length sorted - 1);
       jnum w "tokens_per_sec_median" (median rates);
       jobj_end w
     end;

     if do_ppl then begin
       (* 1. Quality pass over the exact evaluation set. *)
       let nll_total = ref 0.0 and n_tok = ref 0 in
       let full_start = Unix.gettimeofday () in
       Array.iter (fun d -> n_tok := !n_tok + score_doc m d s c (Some nll_total)) docs;
       let full_seconds = Unix.gettimeofday () -. full_start in

       (* 2. Timed passes under a shared wall-clock budget, cycling the corpus. *)
       let ndocs = Array.length docs in
       let rates = Array.make !repeats 0.0 in
       let tok_counts = Array.make !repeats 0 in
       let seconds = Array.make !repeats 0.0 in
       for rep = 0 to !repeats - 1 do
         let cnt = ref 0 and idx = ref 0 in
         let start = Unix.gettimeofday () in
         let elapsed = ref 0.0 in
         let continue_ = ref true in
         while !continue_ do
           cnt := !cnt + score_doc m docs.(!idx mod ndocs) s c None;
           incr idx;
           elapsed := Unix.gettimeofday () -. start;
           if !elapsed >= !time_budget then continue_ := false
         done;
         tok_counts.(rep) <- !cnt;
         seconds.(rep) <- !elapsed;
         rates.(rep) <- float_of_int !cnt /. !elapsed
       done;
       let sorted = Array.copy rates in
       Array.sort compare sorted;
       let nll_per_token = !nll_total /. float_of_int !n_tok in

       jobj w "ppl";
       jint w "docs" ndocs;
       jint w "tokens" !n_tok;
       jint w "repeats" !repeats;
       jnum w "time_budget" !time_budget;
       jnum w "nll_total" !nll_total;
       jnum w "nll_per_token" nll_per_token;
       jnum w "perplexity" (exp nll_per_token);
       jnum w "bits_per_token" (nll_per_token /. log 2.0);
       jnum w "full_pass_seconds" full_seconds;
       jarr w "rates_per_repeat";
       Array.iter (fun v -> jvalf w v) rates;
       jarr_end w;
       jarr w "tokens_per_repeat";
       Array.iter (fun v -> jvali w v) tok_counts;
       jarr_end w;
       jarr w "seconds_per_repeat";
       Array.iter (fun v -> jvalf w v) seconds;
       jarr_end w;
       jnum w "tokens_per_sec_best" sorted.(Array.length sorted - 1);
       jnum w "tokens_per_sec_median" (median rates);
       jobj_end w
     end;

     jobj_end w;
     let text = Buffer.contents w.buf in
     if !json_out <> "" then begin
       let oc = open_out !json_out in
       output_string oc text;
       output_char oc '\n';
       close_out oc
     end;
     print_string text;
     print_newline ()
   with Failure msg ->
     prerr_endline ("error: " ^ msg);
     exit 1)
