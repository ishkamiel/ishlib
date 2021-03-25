package test_has_prefix;

use warnings;
use strict;

use Cwd;
use File::Temp qw/tempfile :seekable/;
use File::Spec;
use Test::More tests => 10;

my $ishlib = File::Spec->catfile(getcwd(), 'ishlib.sh');
my @shells = qw|bash|;
my $dummy_bin = '/bin/ls';

sub simple {
    my ($shell, $bin, $e_ret, $tn) = @_;
    my $test = "simple-$tn";

    my ($fh, $fn) = tempfile();
    print $fh <<EOF;
#! /usr/bin/env $shell
set -e
. $ishlib
BIN_PERL=$bin
if find_or_install BIN_PERL; then
    echo -n "0-\${BIN_PERL}"
else
    echo -n "1-\${BIN_PERL}"
fi
EOF
    close $fh;

    my $e = "$e_ret-" . ($e_ret == 0
        ? qx|which $bin|
        : "$bin"
    );
    chomp $e;

    my $output = qx|$shell $fn / 2>&1|;

    ok($? == 0, "$shell-$test-runs");

    $e eq $output or print STDERR "expected $e, but was $output\n";
    ok($output eq $e, "$shell-$test");

    unlink $fn;
    return;
}

sub simple_installer {
    my ($shell) = @_;
    my $test = "$shell-simple_installer";

    my ($fh, $fn) = tempfile();
    my $bad_name = "NOT_FOUND-someHorribleNameThatWontNeverExist";
    print $fh <<EOF;
#! /usr/bin/env $shell
set -e
. $ishlib
BIN_OK="$bad_name"
BIN_FAIL="$bad_name"
install_ok() {
    printf -v "\${1}" "%s" "/bin/ls"
    return 0
}
install_fail() {
    return 1
}
if find_or_install BIN_OK install_ok; then echo -n "0-"; else echo -n "1-"; fi
echo -n \${BIN_OK}
echo -n "-"
if find_or_install BIN_FAIL install_fail; then echo -n "0-"; else echo -n "1-"; fi
echo -n \${BIN_FAIL}
EOF
    close $fh;

    my $e = "0-$dummy_bin-1-$bad_name";

    my $output = qx|$shell $fn / 2>&1|;

    ok($? == 0, "$shell-$test-runs");

    $e eq $output or print STDERR "expected $e, but was $output\n";
    ok($output eq $e, "$shell-$test");

    unlink $fn;
    return;
}

sub installer_with_args {
    my ($shell) = @_;
    my $test = "$shell-installer_with_args";

    my ($fh, $fn) = tempfile();
    my $bad_name = "NOT_FOUND-someHorribleNameThatWontNeverExist";
    print $fh <<EOF;
#! /usr/bin/env $shell
set -e
. $ishlib
BIN="$bad_name"
installer() {
    if [ \$3 == "ok" ]; then
        printf -v "\${1}" "%s" "$dummy_bin"
        return 0
    fi
    return 1
}
if find_or_install BIN installer \$1 \$2; then echo -n "0-"; else echo -n "1-"; fi
echo -n \${BIN}
EOF
    close $fh;

    my $num = 0;
    for my $t (
        [ "asdfasdfa", "ok", "0-$dummy_bin" ],
        [ "asdfasdfa", "asdfsdaf", "1-$bad_name" ],
    ) {
        my ($arg1, $arg2, $e) = @$t;

        my $output = qx|$shell $fn $arg1 $arg2 2>&1|;

        ok($? == 0, "$shell-$test-runs");
        $e eq $output or print STDERR "expected $e, but was $output\n";
        ok($output eq $e, "$shell-$test" . $num++);
    }

    unlink $fn;
    return;
}

my @testCases = (
    [ "perl", 0, "test01"],
    [ "psadfiuhiugsdgsfdui", 1, "test02"],
);

for my $shell (@shells) {
    for my $t (@testCases) {
        simple($shell, @$t);
    }
    simple_installer($shell);
    installer_with_args($shell);
}

1;
