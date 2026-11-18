// CloudFront viewer-request function. Two jobs, in order:
//
// 1. Redirect any other host (i.e. www) to the apex with a 301, so there is one
//    canonical host. Every page already carries a rel=canonical pointing at the
//    apex, but a redirect is unambiguous and is what someone sharing a www link
//    expects.
//
// 2. Append /index.html to extensionless paths. The origin is an S3 REST
//    endpoint behind OAC, which — unlike an S3 *website* endpoint — has no
//    directory index document, and DefaultRootObject applies only to "/". So
//    /DM-L/12486 looks for the key "DM-L/12486", misses, and falls through to
//    the 403/404 -> /index.html error response, serving the generic SPA shell
//    instead of the prerendered page. That failure is silent, hence the tests in
//    tests/unit/test_web_stack.py.
//
// Paths that keep an extension are real objects (/robots.txt, /sitemap.xml,
// /assets/*, /data/*.json) and must pass through untouched.
//
// ES5 only: the CloudFront Functions runtime is not a full modern JS engine.
var APEX = 'swimtrends.dk';
// Same value as the distribution's response-headers policy (web stack). The
// www 301 below is generated here, so it has to carry HSTS itself.
var HSTS = 'max-age=31536000; includeSubDomains';

function handler(event) {
  var request = event.request;
  var host = request.headers.host && request.headers.host.value;

  // Keep the query: meet pages carry their filters in it (?discipline=&gender=),
  // and inbound utm_* tags should survive too. rawQueryString() (runtime 2.0)
  // is the query exactly as sent, so it is copied verbatim: no decoding, no
  // re-encoding, nothing reinterpreted ('+', '%20', a stray '%').
  if (host && host !== APEX) {
    var qs = request.rawQueryString();
    return {
      statusCode: 301,
      statusDescription: 'Moved Permanently',
      headers: {
        location: { value: 'https://' + APEX + request.uri + (qs ? '?' + qs : '') },
        'strict-transport-security': { value: HSTS },
      },
    };
  }

  var uri = request.uri;
  var last = uri.substring(uri.lastIndexOf('/') + 1);
  if (last === '') {
    request.uri = uri + 'index.html';
  } else if (last.indexOf('.') === -1) {
    request.uri = uri + '/index.html';
  }
  return request;
}
